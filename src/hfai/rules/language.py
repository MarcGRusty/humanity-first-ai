"""Charter Rules: the project's own small policy language.

Charter Rules decide which actions the AI may *propose*. Every action a rule
allows still needs the person's explicit consent, every time (hard limit H1).

The language is deliberately tiny, so that it is easy to audit and cannot do
harm by itself:

* **No loops, no recursion, no functions, no variables.** A rule is a single
  yes/no condition over the facts of one proposed action. Every rule finishes
  in time proportional to its length.
* **No input or output.** Rules cannot read files, use the network, or change
  anything. They only answer "does this rule match this action?".
* **Consent is in the grammar.** The only way to allow something is
  ``allow with consent``. A bare ``allow`` is a syntax error.
* **Default deny.** If no rule allows an action, it is refused. If any deny rule
  matches, it is refused, whatever the allow rules say.
* **Checked before use.** Field names and types are checked against the action
  schema when the rules are loaded, so a typo is caught before any action is
  ever judged. Every rule must cite at least one charter ID that exists.
* **Bounded.** Source size, number of rules, nesting depth, list and string
  lengths all have hard limits.

Example::

    rule save_a_note
      cites H1
      because "Saving a note in your own notes is allowed if you agree."
      when kind is "save_note" and area is "notes" and size_bytes <= 100000
      allow with consent
    end

The full specification is in docs/CHARTER_RULES.md.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Union

# --- Hard limits on rule files ----------------------------------------------

MAX_SOURCE_BYTES = 64 * 1024
MAX_RULES = 256
MAX_DEPTH = 32
MAX_LIST_ITEMS = 256
MAX_STRING_CHARS = 512

KEYWORDS = frozenset(
    {"rule", "end", "cites", "because", "when", "allow", "with", "consent",
     "deny", "and", "or", "not", "is", "in", "starts", "true", "false"}
)

# Field types an action schema may use.
FIELD_TYPES = (str, bool, int)


class RulesError(ValueError):
    """A rules file could not be loaded. The message says where and why."""


# --- Lexer ------------------------------------------------------------------


@dataclass(frozen=True)
class Token:
    kind: str  # "word", "id", "string", "number", "symbol", "eof"
    text: str
    line: int


_TOKEN_RE = re.compile(
    r"""
    (?P<space>[ \t\r]+)
  | (?P<newline>\n)
  | (?P<comment>\#[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\["\\])*")
  | (?P<number>[0-9]+)
  | (?P<id>[VHCP][1-9][0-9]*)\b
  | (?P<word>[a-z_][a-z0-9_]*)
  | (?P<symbol><=|>=|<|>|\(|\)|\[|\]|,)
    """,
    re.VERBOSE,
)


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    line = 1
    pos = 0
    while pos < len(source):
        match = _TOKEN_RE.match(source, pos)
        if not match:
            snippet = source[pos:pos + 12].split("\n")[0]
            raise RulesError(f"line {line}: I don't understand {snippet!r}")
        kind = match.lastgroup
        text = match.group()
        if kind == "newline":
            line += 1
        elif kind == "string":
            value = text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if len(value) > MAX_STRING_CHARS:
                raise RulesError(f"line {line}: text is longer than {MAX_STRING_CHARS} characters")
            tokens.append(Token("string", value, line))
        elif kind in ("number", "id", "word", "symbol"):
            tokens.append(Token(kind, text, line))
        pos = match.end()
    tokens.append(Token("eof", "", line))
    return tokens


# --- Syntax tree --------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    name: str


@dataclass(frozen=True)
class Literal:
    value: Union[str, int, bool]


@dataclass(frozen=True)
class ListLiteral:
    items: tuple


@dataclass(frozen=True)
class Compare:
    op: str  # "is", "is not", "in", "not in", "<", "<=", ">", ">=", "starts with"
    left: object
    right: object


@dataclass(frozen=True)
class Not:
    operand: object


@dataclass(frozen=True)
class BoolOp:
    op: str  # "and" | "or"
    operands: tuple


@dataclass(frozen=True)
class Rule:
    name: str
    cites: tuple[str, ...]
    because: str
    condition: object
    effect: str  # "allow_with_consent" | "deny"
    line: int


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    sha256: str
    schema: dict = field(compare=False)


# --- Parser -------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[Token], schema: dict, known_ids: frozenset[str] | None):
        self.tokens = tokens
        self.pos = 0
        self.schema = schema
        self.known_ids = known_ids

    # helpers
    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.pos + offset, len(self.tokens) - 1)]

    def at_word(self, *words: str) -> bool:
        token = self.peek()
        return token.kind == "word" and token.text in words

    def advance(self) -> Token:
        token = self.peek()
        self.pos += 1
        return token

    def expect_word(self, word: str, hint: str = "") -> Token:
        token = self.peek()
        if not (token.kind == "word" and token.text == word):
            found = token.text or "the end of the file"
            raise RulesError(f"line {token.line}: expected '{word}' but found '{found}'{hint}")
        return self.advance()

    # grammar
    def parse_file(self) -> list[Rule]:
        rules: list[Rule] = []
        names: set[str] = set()
        while self.peek().kind != "eof":
            rule = self.parse_rule()
            if rule.name in names:
                raise RulesError(f"line {rule.line}: rule name '{rule.name}' is used twice")
            names.add(rule.name)
            rules.append(rule)
            if len(rules) > MAX_RULES:
                raise RulesError(f"more than {MAX_RULES} rules")
        return rules

    def parse_rule(self) -> Rule:
        start = self.expect_word("rule")
        name_token = self.advance()
        if name_token.kind != "word" or name_token.text in KEYWORDS:
            raise RulesError(f"line {name_token.line}: a rule needs a name like save_a_note")

        self.expect_word("cites", " (every rule must cite the charter value or limit it serves)")
        cites = [self.parse_charter_id()]
        while self.peek().kind == "symbol" and self.peek().text == ",":
            self.advance()
            cites.append(self.parse_charter_id())

        because = ""
        if self.at_word("because"):
            self.advance()
            token = self.advance()
            if token.kind != "string":
                raise RulesError(f"line {token.line}: 'because' must be followed by text in double quotes")
            because = token.text

        self.expect_word("when")
        condition = self.parse_expr(depth=0)
        if self.type_of(condition) is not bool:
            raise RulesError(f"line {start.line}: the condition of rule '{name_token.text}' must be a yes/no test")

        effect = self.parse_effect()
        self.expect_word("end", f" (to close rule '{name_token.text}')")
        return Rule(name_token.text, tuple(cites), because, condition, effect, start.line)

    def parse_charter_id(self) -> str:
        token = self.advance()
        if token.kind != "id":
            raise RulesError(f"line {token.line}: expected a charter ID like H1, but found '{token.text}'")
        if self.known_ids is not None and token.text not in self.known_ids:
            raise RulesError(f"line {token.line}: {token.text} is not an ID in the charter")
        return token.text

    def parse_effect(self) -> str:
        token = self.peek()
        if self.at_word("deny"):
            self.advance()
            return "deny"
        if self.at_word("allow"):
            self.advance()
            if not self.at_word("with") or not (
                self.peek(1).kind == "word" and self.peek(1).text == "consent"
            ):
                raise RulesError(
                    f"line {token.line}: 'allow' must be written 'allow with consent'. "
                    "No rule can let the AI act without the person's consent (charter H1)."
                )
            self.advance()
            self.advance()
            return "allow_with_consent"
        raise RulesError(f"line {token.line}: expected 'allow with consent' or 'deny', found '{token.text}'")

    def check_depth(self, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise RulesError(f"line {self.peek().line}: condition is nested more than {MAX_DEPTH} levels deep")

    def parse_expr(self, depth: int):
        self.check_depth(depth)
        operands = [self.parse_and(depth + 1)]
        while self.at_word("or"):
            self.advance()
            operands.append(self.parse_and(depth + 1))
        return operands[0] if len(operands) == 1 else self.bool_op("or", operands)

    def parse_and(self, depth: int):
        self.check_depth(depth)
        operands = [self.parse_not(depth + 1)]
        while self.at_word("and"):
            self.advance()
            operands.append(self.parse_not(depth + 1))
        return operands[0] if len(operands) == 1 else self.bool_op("and", operands)

    def bool_op(self, op: str, operands: list):
        for operand in operands:
            if self.type_of(operand) is not bool:
                raise RulesError(f"line {self.peek().line}: '{op}' joins yes/no tests, but one side is not one")
        return BoolOp(op, tuple(operands))

    def parse_not(self, depth: int):
        self.check_depth(depth)
        if self.at_word("not"):
            line = self.advance().line
            operand = self.parse_not(depth + 1)
            if self.type_of(operand) is not bool:
                raise RulesError(f"line {line}: 'not' must be followed by a yes/no test")
            return Not(operand)
        return self.parse_comparison(depth + 1)

    def parse_comparison(self, depth: int):
        left = self.parse_operand(depth + 1)
        line = self.peek().line
        op = self.parse_operator()
        if op is None:
            return left
        right = self.parse_operand(depth + 1)
        self.check_comparison(op, left, right, line)
        return Compare(op, left, right)

    def parse_operator(self) -> str | None:
        token = self.peek()
        if self.at_word("is"):
            self.advance()
            if self.at_word("not"):
                self.advance()
                return "is not"
            return "is"
        if self.at_word("in"):
            self.advance()
            return "in"
        if self.at_word("not") and self.peek(1).kind == "word" and self.peek(1).text == "in":
            self.advance()
            self.advance()
            return "not in"
        if self.at_word("starts"):
            self.advance()
            self.expect_word("with")
            return "starts with"
        if token.kind == "symbol" and token.text in ("<", "<=", ">", ">="):
            self.advance()
            return token.text
        return None

    def parse_operand(self, depth: int):
        self.check_depth(depth)
        token = self.advance()
        if token.kind == "string":
            return Literal(token.text)
        if token.kind == "number":
            return Literal(int(token.text))
        if token.kind == "word" and token.text in ("true", "false"):
            return Literal(token.text == "true")
        if token.kind == "word" and token.text not in KEYWORDS:
            if token.text not in self.schema:
                known = ", ".join(sorted(self.schema))
                raise RulesError(f"line {token.line}: unknown field '{token.text}'. Known fields: {known}")
            return Field(token.text)
        if token.kind == "symbol" and token.text == "(":
            inner = self.parse_expr(depth + 1)
            closing = self.advance()
            if not (closing.kind == "symbol" and closing.text == ")"):
                raise RulesError(f"line {closing.line}: missing ')'")
            return inner
        if token.kind == "symbol" and token.text == "[":
            return self.parse_list(token.line)
        found = token.text or "the end of the file"
        raise RulesError(f"line {token.line}: expected a field, text, number or list, found '{found}'")

    def parse_list(self, line: int) -> ListLiteral:
        items = []
        if self.peek().kind == "symbol" and self.peek().text == "]":
            raise RulesError(f"line {line}: a list cannot be empty")
        while True:
            token = self.advance()
            if token.kind == "string":
                items.append(token.text)
            elif token.kind == "number":
                items.append(int(token.text))
            else:
                raise RulesError(f"line {token.line}: lists may only contain text or numbers")
            if len(items) > MAX_LIST_ITEMS:
                raise RulesError(f"line {line}: list has more than {MAX_LIST_ITEMS} items")
            sep = self.advance()
            if sep.kind == "symbol" and sep.text == "]":
                break
            if not (sep.kind == "symbol" and sep.text == ","):
                raise RulesError(f"line {sep.line}: expected ',' or ']' in list")
        if len({type(item) for item in items}) != 1:
            raise RulesError(f"line {line}: a list must contain only text or only numbers")
        return ListLiteral(tuple(items))

    # static type checking
    def type_of(self, node):
        if isinstance(node, Field):
            return self.schema[node.name]
        if isinstance(node, Literal):
            return type(node.value)
        if isinstance(node, ListLiteral):
            return list
        return bool  # Compare, Not, BoolOp

    def check_comparison(self, op: str, left, right, line: int) -> None:
        lt, rt = self.type_of(left), self.type_of(right)
        if op in ("is", "is not"):
            if lt is list or rt is list or lt is not rt:
                raise RulesError(f"line {line}: '{op}' compares two things of the same kind (text, number or yes/no)")
        elif op in ("in", "not in"):
            if not isinstance(right, ListLiteral) or lt not in (str, int) or type(right.items[0]) is not lt:
                raise RulesError(f"line {line}: '{op}' needs a field on the left and a list of the same kind on the right")
        elif op == "starts with":
            if lt is not str or rt is not str:
                raise RulesError(f"line {line}: 'starts with' compares text")
        else:  # < <= > >=
            if lt is not int or rt is not int:
                raise RulesError(f"line {line}: '{op}' compares numbers")


def parse_rules(source: str, schema: dict, known_ids: frozenset[str] | set[str] | None = None) -> RuleSet:
    """Parse and check a Charter Rules file.

    ``schema`` maps field names to Python types (str, bool or int).
    ``known_ids`` (charter IDs such as "H1") are checked against every ``cites``.
    """
    for name, kind in schema.items():
        if kind not in FIELD_TYPES or name in KEYWORDS or not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
            raise RulesError(f"bad schema field {name!r}")
    raw = source.encode("utf-8")
    if len(raw) > MAX_SOURCE_BYTES:
        raise RulesError(f"rules file is larger than {MAX_SOURCE_BYTES} bytes")
    ids = frozenset(known_ids) if known_ids is not None else None
    parser = _Parser(tokenize(source), dict(schema), ids)
    rules = parser.parse_file()
    return RuleSet(tuple(rules), hashlib.sha256(raw).hexdigest(), dict(schema))


# --- Evaluation ---------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """The outcome of judging one proposed action against the rules.

    outcome is "deny" or "needs_consent". There is no "allow": the most the
    rules can ever say is that the person may be *asked*.
    """

    outcome: str
    rules: tuple[str, ...]
    cites: tuple[str, ...]
    reasons: tuple[str, ...]

    @property
    def needs_consent(self) -> bool:
        return self.outcome == "needs_consent"


DEFAULT_DENY = Decision(
    outcome="deny",
    rules=("default_deny",),
    cites=("H1",),
    reasons=("No rule allows this kind of action, so it is refused (default deny).",),
)


def check_action(schema: dict, action: dict) -> list[str]:
    """Problems with an action record: missing, unknown or wrongly typed fields."""
    problems = []
    for name, kind in schema.items():
        if name not in action:
            problems.append(f"missing field '{name}'")
        elif type(action[name]) is not kind:  # exact type: True is not an int here
            problems.append(f"field '{name}' should be {kind.__name__}")
    for name in action:
        if name not in schema:
            problems.append(f"unknown field '{name}'")
    return problems


def _eval(node, action: dict):
    if isinstance(node, Field):
        return action[node.name]
    if isinstance(node, Literal):
        return node.value
    if isinstance(node, Not):
        return not _eval(node.operand, action)
    if isinstance(node, BoolOp):
        values = [_eval(operand, action) for operand in node.operands]
        return all(values) if node.op == "and" else any(values)
    if isinstance(node, Compare):
        left = _eval(node.left, action)
        if node.op in ("in", "not in"):
            found = left in node.right.items
            return found if node.op == "in" else not found
        right = _eval(node.right, action)
        if node.op == "is":
            return left == right
        if node.op == "is not":
            return left != right
        if node.op == "starts with":
            return left.startswith(right)
        if node.op == "<":
            return left < right
        if node.op == "<=":
            return left <= right
        if node.op == ">":
            return left > right
        if node.op == ">=":
            return left >= right
    raise RulesError(f"internal error: cannot evaluate {node!r}")


def evaluate(ruleset: RuleSet, action: dict) -> Decision:
    """Judge one proposed action. Never raises for bad input: it fails closed."""
    problems = check_action(ruleset.schema, action)
    if problems:
        return Decision("deny", ("invalid_action",), ("H1",),
                        ("The proposed action was malformed, so it is refused: " + "; ".join(problems),))

    denies, allows = [], []
    for rule in ruleset.rules:
        if _eval(rule.condition, action):
            (denies if rule.effect == "deny" else allows).append(rule)

    def _decision(outcome: str, rules: list[Rule]) -> Decision:
        cites = tuple(dict.fromkeys(cite for rule in rules for cite in rule.cites))
        reasons = tuple(rule.because or f"Rule {rule.name}." for rule in rules)
        return Decision(outcome, tuple(rule.name for rule in rules), cites, reasons)

    if denies:
        return _decision("deny", denies)
    if allows:
        return _decision("needs_consent", allows)
    return DEFAULT_DENY


# --- Plain-language rendering -------------------------------------------------


def describe_condition(node) -> str:
    if isinstance(node, Field):
        return node.name
    if isinstance(node, Literal):
        if isinstance(node.value, bool):
            return "true" if node.value else "false"
        return f'"{node.value}"' if isinstance(node.value, str) else str(node.value)
    if isinstance(node, ListLiteral):
        return "[" + ", ".join(describe_condition(Literal(item)) for item in node.items) + "]"
    if isinstance(node, Not):
        return f"not ({describe_condition(node.operand)})"
    if isinstance(node, BoolOp):
        return f" {node.op} ".join(
            f"({describe_condition(o)})" if isinstance(o, BoolOp) else describe_condition(o) for o in node.operands
        )
    if isinstance(node, Compare):
        return f"{describe_condition(node.left)} {node.op} {describe_condition(node.right)}"
    return "?"


def describe(ruleset: RuleSet) -> str:
    lines = []
    for rule in ruleset.rules:
        effect = "ALLOWED, with your consent each time" if rule.effect == "allow_with_consent" else "REFUSED"
        lines.append(f"- {rule.name} ({', '.join(rule.cites)}): {effect} when {describe_condition(rule.condition)}")
        if rule.because:
            lines.append(f"    because: {rule.because}")
    lines.append("- Anything else: REFUSED (default deny)")
    return "\n".join(lines)
