"""The consent gate: no action runs unless a person says yes to that exact action.

Hard limit H1. The gate shows the person, in plain language:

* exactly what will happen (worked out by the guardian, not claimed by the AI);
* the AI's stated reason, clearly labelled as the AI's words;
* the facts the rules judged, and which rule allowed it to be *asked*;
* that saying no is always fine.

Deliberately, there is no "always allow" option in Phase 1. Each action needs
its own yes. The default answer is no.

A ConsentProvider is how the question reaches a person: the terminal (here),
the app (milestone M5), or a scripted stand-in in tests and the demo (always
labelled as simulated).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

from hfai.guardian.actions import Action
from hfai.rules import Decision


@dataclass(frozen=True)
class ConsentRequest:
    action: Action
    decision: Decision
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass(frozen=True)
class ConsentAnswer:
    granted: bool
    note: str = ""


class ConsentProvider(Protocol):
    def ask(self, request: ConsentRequest) -> ConsentAnswer: ...


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def format_request(request: ConsentRequest) -> str:
    """The text shown to the person. Shared by the terminal and the app."""
    facts = request.action.facts
    lines = [
        "┌─ The AI is asking permission to do something ─────────────────",
        "│ What will happen (checked by the safety layer):",
        *[f"│   {line}" for line in request.action.what_will_happen.splitlines()],
        "│",
        f"│ The AI's reason (its own words, may be wrong): {request.action.proposal.reason or '(none given)'}",
        f"│ Can it be undone? {_yes_no(facts['reversible'])}.  Data leaves this device? "
        f"{_yes_no(facts['leaves_device'])}.  Affects other people? {_yes_no(facts['affects_others'])}.",
        f"│ Allowed to ask by rule: {', '.join(request.decision.rules)} (charter {', '.join(request.decision.cites)})",
        "│ Saying no is always fine. Nothing happens unless you say yes.",
        "└────────────────────────────────────────────────────────────────",
    ]
    return "\n".join(lines)


class TerminalConsent:
    """Asks in the terminal. Only 'y' or 'yes' counts as consent."""

    def __init__(self, input_fn=input, output_fn=print):
        self._input = input_fn
        self._output = output_fn

    def ask(self, request: ConsentRequest) -> ConsentAnswer:
        self._output(format_request(request))
        try:
            answer = self._input("Allow this once? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        return ConsentAnswer(answer in ("y", "yes"), "answered in terminal")
