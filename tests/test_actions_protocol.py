"""Actions are built by the guardian, not the AI; the protocol rejects anything unexpected."""

import json

import pytest

from conftest import proposal
from hfai.guardian.actions import (
    PROTECTED_AREAS,
    ActionRegistry,
    Executor,
    ProposalError,
    safe_title,
)
from hfai.worker.protocol import MAX_PROPOSALS, ProtocolError, parse_reply


@pytest.mark.parametrize("title", ["Running goal", "Māori kupu hou", "日本語のメモ", "مرحبا بالعالم", "Привет мир"])
def test_titles_in_any_script(title):
    assert safe_title(title)


@pytest.mark.parametrize("title", ["../secret", "a/b", "a\\b", "", "///", "...."])
def test_unsafe_titles_rejected(title):
    with pytest.raises(ProposalError):
        safe_title(title)


def test_facts_come_from_the_registry_not_the_ai(tmp_path):
    registry = ActionRegistry()
    action = registry.build(proposal(), tmp_path)
    assert action.facts["area"] == "notes"
    assert action.facts["leaves_device"] is False
    assert action.facts["size_bytes"] == len("Run 5 km".encode())


def test_unknown_kind_is_not_an_action(tmp_path):
    assert ActionRegistry().build(proposal(kind="send_email"), tmp_path) is None


def test_fingerprint_covers_content(tmp_path):
    registry = ActionRegistry()
    a = registry.build(proposal(content="one"), tmp_path)
    b = registry.build(proposal(content="two"), tmp_path)
    assert a.fingerprint != b.fingerprint


def test_executors_cannot_target_protected_areas():
    for area in PROTECTED_AREAS:
        bad = Executor("x", area, True, False, False, prepare=lambda p, d: ("", 0), run=lambda p, d: "")
        with pytest.raises(ValueError):
            ActionRegistry([bad])


def test_saving_never_overwrites(tmp_path):
    registry = ActionRegistry()
    for _ in range(2):
        registry.run(registry.build(proposal(), tmp_path), tmp_path)
    assert sorted(p.name for p in (tmp_path / "notes").iterdir()) == ["Goal (2).md", "Goal.md"]


# --- protocol -----------------------------------------------------------------


def reply(**overrides):
    body = {"id": 1, "text": "hi", "proposals": [proposal()]}
    body.update(overrides)
    return json.dumps(body)


def test_valid_reply():
    text, proposals = parse_reply(reply(), 1)
    assert text == "hi" and proposals[0]["kind"] == "save_note"


@pytest.mark.parametrize(
    "line",
    [
        "not json",
        "[1, 2]",
        reply(id=2),
        reply(extra="x"),
        reply(text=5),
        reply(proposals="none"),
        reply(proposals=[proposal()] * (MAX_PROPOSALS + 1)),
        reply(proposals=[{**proposal(), "area": "notes"}]),  # the AI may not claim facts
        reply(proposals=[{**proposal(), "kind": 3}]),
        reply(proposals=[{"kind": "save_note"}]),
        reply(text="x" * 200_000),
    ],
)
def test_bad_replies_rejected(line):
    with pytest.raises(ProtocolError):
        parse_reply(line, 1)
