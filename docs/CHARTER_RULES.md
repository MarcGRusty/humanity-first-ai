# Charter Rules: the project's own policy language

Charter Rules is a tiny language, created for this project, with one job: deciding **which actions the AI may propose to you**. The rules live in [`charter/actions.rules`](../charter/actions.rules), and the code that reads them is in [`src/hfai/rules/language.py`](../src/hfai/rules/language.py).

## Why a language of our own, and why so small

The original request was for "our own programming language so it can remain secure." A full programming language would have made things *less* secure: new compilers have undiscovered bugs, and nobody would have audited it. Instead, Charter Rules is built so that **dangerous things cannot be written in it at all**:

| Guarantee | How |
|---|---|
| **Consent cannot be skipped** | The only way to allow something is `allow with consent`. Writing just `allow` is a syntax error. The most a rule can ever do is let the AI *ask* you. |
| **Default deny** | If no rule allows an action, it is refused. If any `deny` rule matches, it is refused, whatever the allow rules say. |
| **Always finishes** | No loops, no recursion, no functions, no variables. Judging an action takes time proportional to the length of the rules. |
| **Cannot do anything** | No reading or writing files, no network, no changing anything. Rules only answer "does this match?" |
| **Typos caught early** | Field names and types are checked when the rules are loaded. A misspelled field stops the guardian from starting; it never silently matches nothing. |
| **Every rule explains itself** | Each rule must cite at least one charter ID (like `H1`) that really exists, and may give a `because` reason that is shown when it refuses something (charter rule C7). |
| **Fails closed** | A malformed action is refused, never guessed at. |
| **Bounded** | At most 64 KB of rules, 256 rules, 32 levels of nesting, 256 items per list, 512 characters per text. |

## What a rule looks like

```
rule save_a_note
  cites H1
  because "Saving a note in your own notes folder may be proposed; you decide."
  when kind is "save_note" and area is "notes" and size_bytes <= 100000
  allow with consent
end
```

Read it as plain English: *"Rule 'save a note', serving charter limit H1: when the action is saving a note, in the notes area, and it is at most 100,000 bytes, the AI may ask the person."*

## The facts a rule can check

These facts are **worked out by the safety layer itself**, from its own list of actions. They are never taken from what the AI claims.

| Field | Kind | Meaning |
|---|---|---|
| `kind` | text | which action, e.g. `"save_note"` |
| `area` | text | where it acts, e.g. `"notes"`, `"exports"` |
| `target` | text | what it acts on, e.g. a note title |
| `reversible` | yes/no | can it be undone? |
| `leaves_device` | yes/no | would any data leave your device? |
| `affects_others` | yes/no | would it affect anyone else? |
| `size_bytes` | number | how much data is involved |

## Grammar

```
file        := rule*
rule        := "rule" NAME "cites" ID ("," ID)* ["because" TEXT] "when" condition effect "end"
effect      := "allow" "with" "consent" | "deny"
condition   := and_part ("or" and_part)*
and_part    := not_part ("and" not_part)*
not_part    := "not" not_part | comparison
comparison  := operand [operator operand]
operator    := "is" | "is not" | "in" | "not in" | "starts with" | "<" | "<=" | ">" | ">="
operand     := FIELD | TEXT | NUMBER | "true" | "false" | "[" item ("," item)* "]" | "(" condition ")"
NAME, FIELD := lowercase letters, digits and underscores, starting with a letter or underscore
ID          := a charter ID such as V1 or H3
TEXT        := "in double quotes"
```

Comments start with `#`. Line breaks and spaces do not matter.

Type rules: `is` and `is not` compare two things of the same kind. `in` and `not in` need a field on the left and a list of the same kind on the right. `starts with` compares text. `<` `<=` `>` `>=` compare numbers. `and`, `or`, `not` and the whole `when` condition must be yes/no.

## How a decision is made

1. If the action is malformed (missing or extra facts, wrong kinds), it is **refused**.
2. Every rule is checked.
3. If **any** `deny` rule matches, the action is **refused**, citing every matching deny rule.
4. Otherwise, if any `allow with consent` rule matches, **you are asked**.
5. Otherwise it is **refused** by default.

There is no outcome where an action simply happens.

## Changing the rules

`charter/actions.rules` is part of the charter and a **protected area**: changes need human maintainer approval (see [GOVERNANCE.md](../GOVERNANCE.md)). After a reviewed change, maintainers record its new fingerprint with `python -m hfai.guardian integrity --update`; otherwise the guardian refuses to start. To see the current rules in plain language, run `python -m hfai.guardian rules`.
