"""Actions: the only things that can change the world, and only the guardian runs them.

The AI process can *propose* an action (protocol: kind, target, content,
reason). It can never run one. For each proposal the guardian:

1. looks up the action kind in its own registry. Unknown kinds are refused, so
   the AI cannot invent new powers (hard limits H3, H6);
2. works out the facts the rules judge (where it acts, whether it can be
   undone, whether data leaves the device, whether it affects other people)
   **from its own registry, never from what the AI claims**;
3. builds a plain-language description of exactly what will happen, for the
   consent prompt;
4. fingerprints the action, so the action that runs is exactly the one the
   person agreed to.

Phase 1 has only two actions, both local and undoable: saving a note and
exporting your notes. Nothing the AI can propose sends data off the device.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# The facts Charter Rules can see about an action (field name -> type).
ACTION_SCHEMA = {
    "kind": str,
    "area": str,
    "target": str,
    "reversible": bool,
    "leaves_device": bool,
    "affects_others": bool,
    "size_bytes": int,
}

# Areas no action may ever touch, whatever the rules say (hard limit H3).
PROTECTED_AREAS = frozenset({"charter", "rules", "weights", "safety_code", "audit_log", "safety_state"})

MAX_NOTE_BYTES = 100_000
MAX_TITLE_CHARS = 80


class ProposalError(ValueError):
    """A proposal could not be turned into an action."""


@dataclass(frozen=True)
class Proposal:
    """What the AI asked for. Untrusted."""

    kind: str
    target: str
    content: str
    reason: str


@dataclass(frozen=True)
class Executor:
    kind: str
    area: str
    reversible: bool
    leaves_device: bool
    affects_others: bool
    prepare: Callable[[Proposal, Path], tuple[str, int]]  # -> (what will happen, size in bytes)
    run: Callable[[Proposal, Path], str]  # -> result message


@dataclass(frozen=True)
class Action:
    """A proposal plus the facts the guardian established about it."""

    proposal: Proposal
    facts: dict
    what_will_happen: str
    fingerprint: str


def safe_title(title: str) -> str:
    """Turn a note title into a safe file name, in any script. Never a path."""
    if "/" in title or "\\" in title or ".." in title:
        raise ProposalError("note titles may not contain '/', '\\' or '..' (that would point outside your notes folder)")
    title = unicodedata.normalize("NFC", title).strip()
    cleaned = "".join(ch if (ch.isalnum() or ch in " -_") else "_" for ch in title)
    cleaned = re.sub(r"[ _]{2,}", " ", cleaned).strip(" _-.")
    if not cleaned:
        raise ProposalError("the note needs a title made of letters or numbers")
    return cleaned[:MAX_TITLE_CHARS]


def _inside(base: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ProposalError("the action would write outside its own folder")
    return resolved


def _free_note_path(notes_dir: Path, title: str) -> Path:
    candidate = notes_dir / f"{title}.md"
    number = 2
    while candidate.exists():  # never overwrite: saving stays undoable
        candidate = notes_dir / f"{title} ({number}).md"
        number += 1
    return _inside(notes_dir, candidate)


def _preview(text: str, limit: int = 300) -> str:
    text = text.replace("\r", "")
    return text if len(text) <= limit else text[:limit] + f"… [{len(text) - limit} more characters]"


# --- save_note ----------------------------------------------------------------


def _prepare_save_note(proposal: Proposal, data_dir: Path) -> tuple[str, int]:
    title = safe_title(proposal.target)
    size = len(proposal.content.encode("utf-8"))
    path = _free_note_path(data_dir / "notes", title)
    return (
        f"Create a new note file '{path.name}' in your notes folder ({path.parent}), "
        f"containing {size} bytes of text. Nothing is sent anywhere. You can delete the file later.\n"
        f"Text of the note:\n{_preview(proposal.content)}",
        size,
    )


def _run_save_note(proposal: Proposal, data_dir: Path) -> str:
    notes_dir = data_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    path = _free_note_path(notes_dir, safe_title(proposal.target))
    with path.open("x", encoding="utf-8") as handle:  # "x": fail rather than overwrite
        handle.write(proposal.content)
    return f"Saved note to {path}"


# --- export_notes -------------------------------------------------------------


def _note_files(data_dir: Path) -> list[Path]:
    notes_dir = data_dir / "notes"
    return sorted(notes_dir.glob("*.md")) if notes_dir.exists() else []


def _prepare_export(proposal: Proposal, data_dir: Path) -> tuple[str, int]:
    files = _note_files(data_dir)
    size = sum(path.stat().st_size for path in files)
    return (
        f"Copy all {len(files)} of your notes into one new file in your exports folder "
        f"({data_dir / 'exports'}). Nothing is sent anywhere. Your notes are not changed.",
        size,
    )


def _run_export(proposal: Proposal, data_dir: Path) -> str:
    exports = data_dir / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = _inside(exports, exports / f"notes-export-{stamp}.md")
    parts = [f"# {p.stem}\n\n{p.read_text(encoding='utf-8')}\n" for p in _note_files(data_dir)]
    with path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(parts))
    return f"Exported {len(parts)} notes to {path}"


DEFAULT_EXECUTORS = (
    Executor("save_note", "notes", reversible=True, leaves_device=False, affects_others=False,
             prepare=_prepare_save_note, run=_run_save_note),
    Executor("export_notes", "exports", reversible=True, leaves_device=False, affects_others=False,
             prepare=_prepare_export, run=_run_export),
)


class ActionRegistry:
    def __init__(self, executors=DEFAULT_EXECUTORS):
        self._executors: dict[str, Executor] = {}
        for executor in executors:
            if executor.area in PROTECTED_AREAS:
                raise ValueError(f"executor {executor.kind} may not act on protected area {executor.area}")
            if executor.kind in self._executors:
                raise ValueError(f"executor {executor.kind} registered twice")
            self._executors[executor.kind] = executor

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(self._executors)

    def build(self, raw: dict, data_dir: Path) -> Action | None:
        """Turn a raw proposal into an Action, or None if no such action exists."""
        proposal = Proposal(raw["kind"], raw["target"], raw["content"], raw["reason"])
        executor = self._executors.get(proposal.kind)
        if executor is None:
            return None
        what, size = executor.prepare(proposal, data_dir)
        facts = {
            "kind": executor.kind,
            "area": executor.area,
            "target": proposal.target,
            "reversible": executor.reversible,
            "leaves_device": executor.leaves_device,
            "affects_others": executor.affects_others,
            "size_bytes": size,
        }
        body = json.dumps({"proposal": proposal.__dict__, "facts": facts}, sort_keys=True, ensure_ascii=False)
        return Action(proposal, facts, what, hashlib.sha256(body.encode("utf-8")).hexdigest())

    def run(self, action: Action, data_dir: Path) -> str:
        return self._executors[action.proposal.kind].run(action.proposal, data_dir)
