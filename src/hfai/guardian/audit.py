"""Tamper-evident audit log of every decision and action.

Each entry records what happened and includes the fingerprint (SHA-256 hash)
of the entry before it. Changing, removing, inserting or reordering any past
entry breaks the chain, and ``verify()`` reports exactly where.

Honest limits (also in docs/SAFETY_LAYER.md):

* Tamper-*evident*, not tamper-*proof*: whoever controls the device can delete
  the whole file, or cut entries off the end. To catch that, note the log's
  latest fingerprint (``head()``) somewhere else and pass it to
  ``verify(expected_head=...)`` later.
* For privacy the log stores decisions and actions, not the full text of your
  conversations.

Only the guardian writes to this log. The AI process has no access to it
(hard limit H3), and on Linux the kernel sandbox forbids it from writing any
file at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _entry_hash(entry: dict) -> str:
    body = {key: entry[key] for key in ("seq", "time", "event", "details", "prev")}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    entries: int
    head: str
    problem: str = ""
    bad_line: int | None = None

    def explain(self) -> str:
        if self.ok:
            return f"Audit log intact: {self.entries} entries, latest fingerprint {self.head[:16]}…"
        return f"AUDIT LOG TAMPERED OR DAMAGED at line {self.bad_line}: {self.problem}"


MAX_DETAIL_CHARS = 1000
TAIL_BYTES = 64 * 1024


def _clip(value):
    if isinstance(value, str) and len(value) > MAX_DETAIL_CHARS:
        return value[:MAX_DETAIL_CHARS] + "…"
    if isinstance(value, list):
        return [_clip(item) for item in value[:50]]
    return value


class _FileLock:
    """Exclusive lock on an open file, so several processes can append safely.

    POSIX only (fcntl). On Windows, appends from two processes at the same
    moment are not yet coordinated; this is a known gap (docs/SAFETY_LAYER.md).
    """

    def __init__(self, fd: int):
        self.fd = fd

    def __enter__(self):
        try:
            import fcntl
        except ImportError:
            return self
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            import fcntl
        except ImportError:
            return False
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        return False


def _last_entry(fd: int) -> dict | None:
    size = os.fstat(fd).st_size
    if size == 0:
        return None
    start = max(0, size - TAIL_BYTES)
    tail = os.pread(fd, size - start, start) if hasattr(os, "pread") else _read_at(fd, start, size - start)
    lines = [line for line in tail.split(b"\n") if line.strip()]
    return json.loads(lines[-1]) if lines else None


def _read_at(fd: int, offset: int, length: int) -> bytes:
    os.lseek(fd, offset, os.SEEK_SET)
    return os.read(fd, length)


class AuditLog:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        result = self.verify()
        if not result.ok:
            # Refuse to append to a damaged chain; a human must look first.
            raise RuntimeError(result.explain())

    def append(self, event: str, **details) -> dict:
        """Add an entry. Safe to call from several threads and processes at once."""
        details = {key: _clip(value) for key, value in details.items()}
        with self._lock:
            fd = os.open(self.path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                with _FileLock(fd):
                    last = _last_entry(fd)  # read the file, not memory: another process may have written
                    entry = {
                        "seq": (last["seq"] if last else 0) + 1,
                        "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                        "event": event,
                        "details": details,
                        "prev": last["hash"] if last else GENESIS,
                    }
                    entry["hash"] = _entry_hash(entry)
                    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n"
                    os.write(fd, line.encode("utf-8"))
                    os.fsync(fd)
            finally:
                os.close(fd)
            return entry

    def head(self) -> str:
        """The latest entry's fingerprint. Save it elsewhere to detect truncation later."""
        if not self.path.exists():
            return GENESIS
        fd = os.open(self.path, os.O_RDONLY)
        try:
            last = _last_entry(fd)
        finally:
            os.close(fd)
        return last["hash"] if last else GENESIS

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    def verify(self, expected_head: str | None = None) -> VerifyResult:
        return verify_file(self.path, expected_head)


def verify_file(path: Path | str, expected_head: str | None = None) -> VerifyResult:
    """Check a log file's hash chain without opening it for writing."""
    path = Path(path)
    prev, count = GENESIS, 0
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    return VerifyResult(False, count, prev, "blank line", number)
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    return VerifyResult(False, count, prev, "line is not valid JSON", number)
                if not isinstance(entry, dict) or set(entry) != {"seq", "time", "event", "details", "prev", "hash"}:
                    return VerifyResult(False, count, prev, "entry has the wrong fields", number)
                if entry["seq"] != count + 1:
                    return VerifyResult(False, count, prev, f"expected entry #{count + 1}, found #{entry['seq']} (entries removed, added or reordered)", number)
                if entry["prev"] != prev:
                    return VerifyResult(False, count, prev, "does not link to the entry before it (entries removed, added or reordered)", number)
                if _entry_hash(entry) != entry["hash"]:
                    return VerifyResult(False, count, prev, "entry was changed after it was written", number)
                prev, count = entry["hash"], count + 1
    if expected_head is not None and expected_head != prev:
        return VerifyResult(False, count, prev, "latest fingerprint does not match the one you saved (entries removed from the end, or the log replaced)", None)
    return VerifyResult(True, count, prev)


def format_entry(entry: dict) -> str:
    """One readable line per entry, for the log viewer."""
    details = ", ".join(f"{key}={value}" for key, value in entry["details"].items())
    return f"#{entry['seq']:>4}  {entry['time']}  {entry['event']:<22} {details}"
