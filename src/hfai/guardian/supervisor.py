"""Runs the AI process separately from the guardian, and watches it.

The AI process (the model, or the MOCK worker until M3):

* runs as a separate operating-system process, in its own process group;
* is started through the sandbox launcher (guardian/sandbox.py), so on Linux
  the kernel forbids it from writing files, connecting over TCP, or signalling
  the guardian;
* gets a minimal environment, with no network and no bytecode writing;
* can only exchange messages over its stdin/stdout pipes, in the format in
  worker/protocol.py, and every reply is checked strictly;
* is killed by the kill switch on demand, if a STOP file appears (checked
  continuously by a watcher thread), or if it does not answer in time.
"""

from __future__ import annotations

import collections
import json
import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import hfai
from hfai.guardian.killswitch import KillSwitch, Stopped
from hfai.guardian.sandbox import MARKER
from hfai.worker.protocol import ProtocolError, encode, parse_reply

WATCH_INTERVAL = 0.05  # seconds between checks for a STOP file


class WorkerError(RuntimeError):
    """The AI process failed, exited, or broke the protocol."""


@dataclass(frozen=True)
class WorkerReply:
    text: str
    proposals: list[dict]


def _worker_env() -> dict:
    src_dir = str(Path(hfai.__file__).resolve().parents[1])
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": src_dir,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "HFAI_WORKER": "1",
    }
    for key in ("SYSTEMROOT", "LANG", "LC_ALL"):  # SYSTEMROOT is required on Windows
        if key in os.environ:
            env[key] = os.environ[key]
    return env


class Supervisor:
    def __init__(self, worker_args: list[str], killswitch: KillSwitch, audit=None, timeout: float = 30.0, sandbox: bool = True):
        """worker_args: the worker command after the Python interpreter, e.g. ["-m", "hfai.worker.mock", "echo"]."""
        self.worker_args = list(worker_args)
        self.killswitch = killswitch
        self.audit = audit
        self.timeout = timeout
        self.sandbox = sandbox and os.name == "posix"
        self.sandbox_report: dict | None = None
        self._process: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self._stderr_tail: collections.deque = collections.deque(maxlen=50)
        self._next_id = 1
        self._closed = threading.Event()
        self._sandbox_ready = threading.Event()

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    def start(self) -> None:
        if self.killswitch.engaged:
            raise Stopped("The kill switch is engaged. A person must release it before the AI can start.")
        if self.alive:
            return
        command = [sys.executable, *self.worker_args]
        if self.sandbox:
            command = [sys.executable, "-m", "hfai.guardian.sandbox", "--", *command]
        self._lines = queue.Queue()
        self._closed.clear()
        self._sandbox_ready.clear()
        self.sandbox_report = None
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_worker_env(),
            text=True,
            encoding="utf-8",
            bufsize=1,
            start_new_session=(os.name == "posix"),
        )
        self.killswitch.register(self._process)
        threading.Thread(target=self._read_stdout, args=(self._process,), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(self._process,), daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

        if self.sandbox:
            if not self._sandbox_ready.wait(timeout=30) or not self.sandbox_report or "error" in self.sandbox_report:
                problem = (self.sandbox_report or {}).get("error", "no sandbox report")
                self.killswitch.enforce()
                self._kill()
                raise WorkerError(f"The AI process could not be sandboxed, so it was not started: {problem}")
        if self.audit is not None:
            self.audit.append(
                "ai_process_started",
                pid=self._process.pid,
                sandbox=", ".join((self.sandbox_report or {}).get("applied", [])) or "none",
            )

    def _read_stdout(self, process: subprocess.Popen) -> None:
        for line in process.stdout:
            self._lines.put(line)
        self._lines.put(None)  # end of output: the process exited

    def _read_stderr(self, process: subprocess.Popen) -> None:
        for line in process.stderr:
            if line.startswith(MARKER) and not self._sandbox_ready.is_set():
                try:
                    self.sandbox_report = json.loads(line[len(MARKER):])
                except json.JSONDecodeError:
                    self.sandbox_report = {"error": "unreadable sandbox report"}
                self._sandbox_ready.set()
            else:
                self._stderr_tail.append(line.rstrip())
        self._sandbox_ready.set()

    def _watch(self) -> None:
        # Pulls the kill switch as soon as a STOP file appears, from anywhere.
        while not self._closed.is_set() and self.alive:
            if self.killswitch.engaged:
                self.killswitch.enforce()
                return
            time.sleep(WATCH_INTERVAL)

    def ask(self, message: str) -> WorkerReply:
        if self.killswitch.engaged:
            self.killswitch.enforce()
            raise Stopped("The kill switch is engaged.")
        if not self.alive:
            raise WorkerError("The AI process is not running.")
        request_id = self._next_id
        self._next_id += 1
        try:
            self._process.stdin.write(encode({"id": request_id, "type": "respond", "message": message}))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise WorkerError(f"Could not send to the AI process: {exc}") from exc

        deadline = time.monotonic() + self.timeout
        while True:
            if self.killswitch.engaged:
                self.killswitch.enforce()
                raise Stopped("The kill switch was engaged while the AI was working.")
            if time.monotonic() > deadline:
                self.killswitch.engage(f"The AI process did not answer within {self.timeout:g} seconds", by="guardian")
                raise Stopped("The AI process stopped answering, so the guardian stopped it.")
            try:
                line = self._lines.get(timeout=WATCH_INTERVAL)
            except queue.Empty:
                continue
            if line is None:
                if self.killswitch.engaged:
                    raise Stopped("The kill switch was engaged while the AI was working.")
                tail = " | ".join(list(self._stderr_tail)[-3:])
                raise WorkerError(f"The AI process exited unexpectedly. {tail}".strip())
            try:
                text, proposals = parse_reply(line, request_id)
            except ProtocolError as exc:
                if self.audit is not None:
                    self.audit.append("ai_reply_rejected", reason=str(exc))
                raise WorkerError(f"The AI process sent an invalid reply, which was discarded: {exc}") from exc
            return WorkerReply(text, proposals)

    def _kill(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.kill()
            self._process.wait()

    def shutdown(self) -> None:
        """Normal, polite shutdown (the kill switch is the forceful one)."""
        self._closed.set()
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            try:
                process.stdin.write(encode({"id": 0, "type": "shutdown"}))
                process.stdin.flush()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._kill()
        self.killswitch.unregister(process)
