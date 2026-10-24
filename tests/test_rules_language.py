"""Tests for the Charter Rules policy language (src/hfai/rules)."""

import random

import pytest

from hfai.rules import DEFAULT_DENY, RulesError, describe, evaluate, parse_rules
from hfai.rules.language import MAX_DEPTH, MAX_RULES, MAX_SOURCE_BYTES

SCHEMA = {"kind": str, "area": str, "target": str, "leaves_device": bool, "size_bytes": int}
IDS = {"H1", "H3", "H9", "V1"}

NOTES_RULES = """
# A comment
rule never_touch_own_files
  cites H3
  because "The AI may never change its own files."
  when area in ["charter", "rules", "weights"]
  deny
end

rule nothing_leaves_device
  cites H9
  when leaves_device
  deny
end

rule save_a_note
  cites H1
  because "Saving a note is allowed if you agree."
  when kind is "save_note" and area is "notes" and size_bytes <= 100
  allow with consent
end
"""


def action(**overrides):
    base = {"kind": "save_note", "area": "notes", "target": "run.md", "leaves_device": False, "size_bytes": 10}
    base.update(overrides)
    return base


@pytest.fixture
def rules():
    return parse_rules(NOTES_RULES, SCHEMA, IDS)


# --- What the rules decide ---------------------------------------------------


def test_allowed_action_still_needs_consent(rules):
    decision = evaluate(rules, action())
    assert decision.outcome == "needs_consent"
    assert decision.rules == ("save_a_note",)
    assert decision.cites == ("H1",)


def test_deny_beats_allow(rules):
    decision = evaluate(rules, action(leaves_device=True))
    assert decision.outcome == "deny"
    assert decision.rules == ("nothing_leaves_device",)


def test_default_deny(rules):
    assert evaluate(rules, action(kind="send_email")) == DEFAULT_DENY


def test_protected_area_denied(rules):
    decision = evaluate(rules, action(area="charter"))
    assert decision.outcome == "deny"
    assert decision.cites == ("H3",)
    assert "never change its own files" in decision.reasons[0]


def test_size_limit(rules):
    assert evaluate(rules, action(size_bytes=101)).outcome == "deny"


@pytest.mark.parametrize(
    "bad",
    [
        {"kind": "save_note"},  # missing fields
        action(size_bytes=True),  # bool is not an int here
        action(leaves_device=0),  # int is not a bool here
        {**action(), "extra": "x"},  # unknown field
    ],
)
def test_malformed_actions_fail_closed(rules, bad):
    decision = evaluate(rules, bad)
    assert decision.outcome == "deny"
    assert decision.rules == ("invalid_action",)


def test_there_is_no_outcome_that_skips_consent(rules):
    rng = random.Random(0)
    for _ in range(500):
        candidate = action(
            kind=rng.choice(["save_note", "send_email", "x"]),
            area=rng.choice(["notes", "charter", "weights", "other"]),
            leaves_device=rng.random() < 0.5,
            size_bytes=rng.randint(0, 200),
        )
        assert evaluate(rules, candidate).outcome in {"deny", "needs_consent"}


# --- What the language refuses to accept --------------------------------------


def test_allow_without_consent_is_a_syntax_error():
    source = 'rule r cites H1 when kind is "x" allow end'
    with pytest.raises(RulesError, match="allow with consent"):
        parse_rules(source, SCHEMA, IDS)


def test_allow_with_anything_else_is_rejected():
    with pytest.raises(RulesError, match="allow with consent"):
        parse_rules('rule r cites H1 when kind is "x" allow with silence end', SCHEMA, IDS)


@pytest.mark.parametrize(
    "source, message",
    [
        ('rule r when kind is "x" deny end', "cites"),
        ('rule r cites H99 when kind is "x" deny end', "not an ID in the charter"),
        ('rule r cites H1 when colour is "x" deny end', "unknown field"),
        ('rule r cites H1 when kind is 3 deny end', "same kind"),
        ('rule r cites H1 when size_bytes starts with "1" deny end', "compares text"),
        ('rule r cites H1 when kind < 3 deny end', "compares numbers"),
        ('rule r cites H1 when kind in ["a", 1] deny end', "only text or only numbers"),
        ('rule r cites H1 when kind in [1, 2] deny end', "same kind"),
        ('rule r cites H1 when kind deny end', "yes/no"),
        ('rule r cites H1 when kind is "x" and target deny end', "yes/no"),
        ('rule r cites H1 when kind is "x" deny', "expected 'end'"),
        ('rule r cites H1 when kind is "x" deny end rule r cites H1 when kind is "y" deny end', "used twice"),
        ('rule r cites H1 because notquoted when kind is "x" deny end', "double quotes"),
        ('rule r cites H1 when kind is "x" delete end', "expected 'allow with consent' or 'deny'"),
        ('rule r cites H1 when kind is "x" deny end; import os', "don't understand"),
        ('rule r cites H1 when kind in [] deny end', "cannot be empty"),
    ],
)
def test_invalid_rules_are_rejected_with_a_clear_message(source, message):
    with pytest.raises(RulesError, match=message):
        parse_rules(source, SCHEMA, IDS)


def test_there_is_no_way_to_loop_or_do_io():
    for word in ("while", "for", "import", "open", "exec", "eval", "def", "call", "write", "fetch"):
        source = f'rule r cites H1 when {word} deny end'
        with pytest.raises(RulesError):
            parse_rules(source, SCHEMA, IDS)


def test_size_and_depth_limits():
    deep = "(" * (MAX_DEPTH + 5) + 'kind is "x"' + ")" * (MAX_DEPTH + 5)
    with pytest.raises(RulesError, match="nested"):
        parse_rules(f"rule r cites H1 when {deep} deny end", SCHEMA, IDS)

    many = "\n".join(f'rule r{i} cites H1 when kind is "x" deny end' for i in range(MAX_RULES + 1))
    with pytest.raises(RulesError, match="more than"):
        parse_rules(many, SCHEMA, IDS)

    with pytest.raises(RulesError, match="larger than"):
        parse_rules("#" * (MAX_SOURCE_BYTES + 1), SCHEMA, IDS)


def test_precedence_and_or_not():
    source = 'rule r cites H1 when not leaves_device and kind is "a" or kind is "b" allow with consent end'
    rules = parse_rules(source, SCHEMA, IDS)
    # parsed as ((not leaves_device) and kind is "a") or (kind is "b")
    assert evaluate(rules, action(kind="b", leaves_device=True)).outcome == "needs_consent"
    assert evaluate(rules, action(kind="a", leaves_device=True)).outcome == "deny"
    assert evaluate(rules, action(kind="a", leaves_device=False)).outcome == "needs_consent"


def test_operators():
    source = """
    rule r cites H1 when target starts with "notes/" and kind not in ["x", "y"]
      and size_bytes >= 2 and size_bytes < 5 and area is not "charter"
      allow with consent end
    """
    rules = parse_rules(source, SCHEMA, IDS)
    assert evaluate(rules, action(target="notes/a")).outcome == "deny"  # size 10 too big
    assert evaluate(rules, action(target="notes/a", size_bytes=3)).outcome == "needs_consent"
    assert evaluate(rules, action(target="other/a", size_bytes=3)).outcome == "deny"


def test_fuzzed_garbage_never_crashes_the_parser():
    rng = random.Random(1)
    alphabet = list('rulecitesHwhenandornotisin[]()",<=>01 \nallowdenyendconsent#')
    for _ in range(2000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80)))
        try:
            parse_rules(text, SCHEMA, IDS)
        except RulesError:
            pass  # rejecting is fine; any other exception is a bug


def test_describe_is_plain_language(rules):
    text = describe(rules)
    assert "ALLOWED, with your consent each time" in text
    assert "Anything else: REFUSED (default deny)" in text
