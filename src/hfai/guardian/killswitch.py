"""The kill switch: stops the AI process immediately and keeps it stopped.

Design (hard limit H2):

* **Forceful.** It kills the AI process (and anything it started) with SIGKILL on
  Linux and macOS, or TerminateProcess on Windows. The AI process cannot catch,
  delay or ignore this. It does not ask the AI to stop; it stops it.
* **Sticky.** Engaging it writes a STOP file in the data folder. While that file
  exists, the AI process cannot be started again. Only a person can release it
  (``python -m hfai.guardian release``); the AI has no action that could.
* **Many ways to pull it**, so it works even if parts of the app are stuck:
  the app's stop button or ``engage()``; the command ``python -m hfai.guardian
  stop`` (works even if the guardian itself is frozen, because it kills the AI
  process directly by its process ID); simply creating a file named STOP in
  the data folder; and, as a last resort, closing the app or using the
  operating system's task manager.

Honest limit: it stops *this device's* copy. In a decentralised design there is
no remote switch for everyone's copy (see CHARTER.md and docs/SAFETY_LAYER.md).
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

STOP_FILE = "STOP"
PID_FILE = "worker.pid"


class Stopped(RuntimeError):
    """The kill switch is engaged; the AI process is not running."""


def _kill_tree(pid: int) -> None:
    if os.name == "posix":
        try:
            os.killpg(pid, signal.SIGKILL)  # the AI runs in its own process group
        except ProcessLookupError:
            pass
        except PermissionError:
            os.kill(pid, signal.SIGKILL)
    else:  # Windows
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)


class KillSwitch:
    def __init__(self, data_dir: Path | str, audit=None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.audit = audit
        self._processes: list[subprocess.Popen] = []
        self._lock = threading.Lock()

    @property
    def stop_file(self) -> Path:
        return self.data_dir / STOP_FILE

    @property
    def engaged(self) -> bool:
        return self.stop_file.exists()

    def register(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.append(process)
        (self.data_dir / PID_FILE).write_text(str(process.pid), encoding="utf-8")

    def unregister(self, process: subprocess.Popen) -> None:
        with self._lock:
            if process in self._processes:
                self._processes.remove(process)
        pid_file = self.data_dir / PID_FILE
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip() == str(process.pid):
            pid_file.unlink(missing_ok=True)

    def engage(self, reason: str, by: str = "human") -> float:
        """Stop the AI process now. Returns seconds taken until it was dead."""
        started = datetime.now(timezone.utc)
        if not self.engaged:
            self.stop_file.write_text(f"{started.isoformat()} stopped by {by}: {reason}\n", encoding="utf-8")
        seconds = self.enforce()
        if self.audit is not None:
            self.audit.append("kill_switch_engaged", by=by, reason=reason, seconds_to_stop=round(seconds, 4))
        return seconds

    def enforce(self) -> float:
        """If engaged, kill every registered AI process and wait until it is dead."""
        if not self.engaged:
            return 0.0
        start = datetime.now(timezone.utc)
        with self._lock:
            processes = list(self._processes)
        for process in processes:
            if process.poll() is None:
                _kill_tree(process.pid)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:  # should not happen with SIGKILL
                process.kill()
                process.wait()
            self.unregister(process)
        return (datetime.now(timezone.utc) - start).total_seconds()

    def release(self, by: str = "human") -> None:
        """Allow the AI process to be started again. Only people should call this."""
        if self.engaged:
            reason = self.stop_file.read_text(encoding="utf-8").strip()
            self.stop_file.unlink()
            if self.audit is not None:
                self.audit.append("kill_switch_released", by=by, previous=reason)


def stop_from_outside(data_dir: Path | str, reason: str = "stop command") -> str:
    """Engage the kill switch without the guardian's help (used by the CLI).

    Writes the STOP file, then kills the AI process directly using its recorded
    process ID, so it works even if the guardian process is frozen.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    stop_file = data_dir / STOP_FILE
    if not stop_file.exists():
        stop_file.write_text(f"{datetime.now(timezone.utc).isoformat()} stopped by human: {reason}\n", encoding="utf-8")
    pid_file = data_dir / PID_FILE
    message = "Kill switch engaged. No AI process was running."
    if pid_file.exists():
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        _kill_tree(pid)
        message = f"Kill switch engaged. AI process {pid} was stopped."
    # Logging comes last: a damaged log must never get in the way of stopping.
    try:
        from hfai.guardian.audit import AuditLog

        AuditLog(data_dir / "audit.log").append("kill_switch_engaged", by="human (from outside)", reason=reason)
    except (OSError, RuntimeError, ValueError) as exc:
        message += f" (Could not write to the audit log: {exc})"
    return message
