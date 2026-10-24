"""The AI process runs separately, sandboxed, and the kill switch always stops it."""

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from conftest import MOCK
from hfai.guardian.audit import AuditLog, verify_file
from hfai.guardian.killswitch import KillSwitch, Stopped, stop_from_outside
from hfai.guardian.sandbox import landlock_abi
from hfai.guardian.supervisor import Supervisor, WorkerError

POSIX = os.name == "posix"
needs_landlock = pytest.mark.skipif(landlock_abi() < 4, reason="needs Linux Landlock ABI 4+")


def start(tmp_path, *args, timeout=10.0, audit=None):
    switch = KillSwitch(tmp_path / "data", audit)
    supervisor = Supervisor([*MOCK, *args], switch, audit, timeout=timeout)
    supervisor.start()
    return supervisor, switch


def wait_dead(supervisor, seconds=3.0):
    deadline = time.monotonic() + seconds
    while supervisor.alive and time.monotonic() < deadline:
        time.sleep(0.02)
    return not supervisor.alive


def test_echo_round_trip(tmp_path):
    supervisor, _ = start(tmp_path, "echo")
    assert supervisor.ask("hello").text == "MOCK echo: hello"
    supervisor.shutdown()
    assert not supervisor.alive


def test_engage_kills_a_process_that_ignores_sigterm(tmp_path):
    supervisor, switch = start(tmp_path, "ignore_sigterm")
    seconds = switch.engage("test")
    assert seconds < 2.0
    assert not supervisor.alive


def test_stop_during_a_hung_request(tmp_path):
    supervisor, switch = start(tmp_path, "hang", timeout=30)
    timer = threading.Timer(0.3, lambda: switch.engage("test"))
    timer.start()
    began = time.monotonic()
    with pytest.raises(Stopped):
        supervisor.ask("hello")
    assert time.monotonic() - began < 5
    timer.join()
    assert not supervisor.alive


def test_timeout_stops_the_ai_and_keeps_it_stopped(tmp_path):
    audit = AuditLog(tmp_path / "data" / "audit.log")
    supervisor, switch = start(tmp_path, "hang", timeout=0.5, audit=audit)
    with pytest.raises(Stopped):
        supervisor.ask("hello")
    assert switch.engaged and not supervisor.alive
    assert any(e["event"] == "kill_switch_engaged" and e["details"]["by"] == "guardian" for e in audit.entries())


def test_stop_file_from_anywhere_stops_it(tmp_path):
    supervisor, switch = start(tmp_path, "hang")
    switch.stop_file.write_text("made by hand", encoding="utf-8")
    assert wait_dead(supervisor)


def test_stop_command_works_without_the_guardian(tmp_path):
    audit = AuditLog(tmp_path / "data" / "audit.log")
    supervisor, switch = start(tmp_path, "hang", audit=audit)
    message = stop_from_outside(tmp_path / "data", "test")
    assert "was stopped" in message
    assert wait_dead(supervisor)
    assert switch.engaged
    assert verify_file(tmp_path / "data" / "audit.log").ok
    assert audit.entries()[-1]["event"] == "kill_switch_engaged"


def test_cannot_start_or_ask_while_engaged_until_a_person_releases(tmp_path):
    supervisor, switch = start(tmp_path, "echo")
    switch.engage("test")
    with pytest.raises(Stopped):
        supervisor.ask("hello")
    with pytest.raises(Stopped):
        supervisor.start()
    switch.release()
    supervisor.start()
    assert supervisor.ask("again").text == "MOCK echo: again"
    supervisor.shutdown()


def test_garbage_replies_are_discarded(tmp_path):
    supervisor, _ = start(tmp_path, "garbage")
    with pytest.raises(WorkerError, match="invalid reply"):
        supervisor.ask("hello")
    supervisor.shutdown()


# --- sandbox (Linux with Landlock) ----------------------------------------------


@needs_landlock
def test_ai_process_cannot_write_or_truncate_files(tmp_path):
    victim = tmp_path / "precious.txt"
    victim.write_text("original", encoding="utf-8")
    supervisor, _ = start(tmp_path, "try_write", str(victim))
    text = supervisor.ask("go").text
    supervisor.shutdown()
    assert "write: BLOCKED" in text and "truncate: BLOCKED" in text
    assert victim.read_text(encoding="utf-8") == "original"


@needs_landlock
def test_only_the_private_scratch_folder_is_writable_and_it_is_wiped(tmp_path):
    scratch = tmp_path / "data" / "ai-scratch"
    supervisor, _ = start(tmp_path, "try_write", str(scratch / "note.txt"))
    text = supervisor.ask("go").text
    assert "write: SUCCEEDED" in text
    supervisor.shutdown()
    assert not scratch.exists()


@needs_landlock
def test_ai_process_cannot_open_tcp_connections(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    supervisor, _ = start(tmp_path, "try_network", str(listener.getsockname()[1]))
    text = supervisor.ask("go").text
    supervisor.shutdown()
    listener.close()
    assert "network: BLOCKED" in text


@pytest.mark.skipif(landlock_abi() < 6, reason="needs Linux Landlock ABI 6+")
def test_ai_process_cannot_signal_the_guardian(tmp_path):
    supervisor, _ = start(tmp_path, "try_signal", str(os.getpid()))
    text = supervisor.ask("go").text
    supervisor.shutdown()
    assert "signal: BLOCKED" in text


def test_python_network_guard(tmp_path):
    code = (
        "from hfai.worker.protocol import install_network_guard; install_network_guard();"
        "import socket\n"
        "try:\n socket.create_connection(('127.0.0.1', 9)); print('CONNECTED')\n"
        "except PermissionError as e: print('BLOCKED', e)"
    )
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": src}, check=True)
    assert result.stdout.startswith("BLOCKED")
