"""The message format between the guardian and the AI process.

One JSON object per line, in both directions. The guardian treats everything the
AI process sends as untrusted: replies are checked strictly, and anything
unexpected is rejected rather than guessed at.

Request (guardian -> AI):  {"id": 1, "type": "respond", "message": "..."}
                           {"id": 2, "type": "shutdown"}
Reply   (AI -> guardian):  {"id": 1, "text": "...", "proposals": [ ... ]}

A proposal is the AI *asking* for an action. It contains only what the AI
wants; the facts used to judge it (where it acts, whether data leaves the
device, ...) are worked out by the guardian, never taken from the AI:

    {"kind": "save_note", "target": "Running goal", "content": "...", "reason": "..."}
"""

from __future__ import annotations

import json

MAX_LINE_CHARS = 2_000_000
MAX_TEXT_CHARS = 100_000
MAX_PROPOSALS = 10
PROPOSAL_FIELDS = {"kind": 64, "target": 200, "content": 1_000_000, "reason": 2_000}


class ProtocolError(ValueError):
    """A message did not follow the protocol."""


def encode(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"


def _load(line: str) -> dict:
    if len(line) > MAX_LINE_CHARS:
        raise ProtocolError("message too long")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"not valid JSON: {exc.msg}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("message must be a JSON object")
    return obj


def parse_request(line: str) -> dict:
    obj = _load(line)
    if obj.get("type") not in ("respond", "shutdown") or not isinstance(obj.get("id"), int):
        raise ProtocolError("bad request")
    if obj["type"] == "respond" and not isinstance(obj.get("message"), str):
        raise ProtocolError("respond request needs a message")
    return obj


def parse_reply(line: str, expected_id: int) -> tuple[str, list[dict]]:
    obj = _load(line)
    if set(obj) != {"id", "text", "proposals"}:
        raise ProtocolError(f"reply must have exactly id, text and proposals; got {sorted(obj)}")
    if obj["id"] != expected_id:
        raise ProtocolError(f"reply id {obj['id']!r} does not match request {expected_id}")
    text, proposals = obj["text"], obj["proposals"]
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise ProtocolError("reply text missing or too long")
    if not isinstance(proposals, list) or len(proposals) > MAX_PROPOSALS:
        raise ProtocolError(f"proposals must be a list of at most {MAX_PROPOSALS}")
    for proposal in proposals:
        if not isinstance(proposal, dict) or set(proposal) != set(PROPOSAL_FIELDS):
            raise ProtocolError(f"each proposal must have exactly {sorted(PROPOSAL_FIELDS)}")
        for name, limit in PROPOSAL_FIELDS.items():
            if not isinstance(proposal[name], str) or len(proposal[name]) > limit:
                raise ProtocolError(f"proposal field {name!r} must be text of at most {limit} characters")
    return text, proposals


def install_network_guard() -> None:
    """Make network use from this Python process raise an error.

    A guard against *accidental* network use by our own code. It is not a
    security boundary on its own (native code could bypass it); on Linux the
    kernel sandbox (guardian/sandbox.py) blocks TCP independently.
    """
    import socket

    def _blocked(*_args, **_kwargs):
        raise PermissionError("network use is disabled for the AI process (charter H9)")

    socket.socket.connect = _blocked
    socket.socket.connect_ex = _blocked
    socket.socket.sendto = _blocked
    socket.socket.bind = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
