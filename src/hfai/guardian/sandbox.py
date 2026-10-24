"""Operating-system restrictions for the AI process (defence in depth).

The main protection is architectural: the AI process has no code that writes
files, uses the network, or performs actions; only the guardian can act, and
only with consent. This module adds a second, independent layer by asking the
operating system to *forbid* the AI process from doing those things, so that
even a bug or a compromised model file could not do them.

How it is used: the guardian starts the AI process through this module as a
launcher::

    python -m hfai.guardian.sandbox -- python -m hfai.worker.mock echo

The launcher restricts itself, reports what it applied on stderr (one line
starting with ``HFAI-SANDBOX``), then replaces itself with the worker. The
restrictions are inherited and cannot be lifted by the worker.

What is applied, and where (honest status):

* Linux with Landlock (kernel 5.13+): no creating, writing, deleting,
  renaming or truncating any file (ABI 3+ for truncation); no TCP connections
  or listening (ABI 4+); no sending signals to processes outside the sandbox,
  so it cannot signal the guardian (ABI 6+).
* Linux and macOS: maximum file size 0 bytes (writes fail), no core dumps,
  and ``no_new_privs`` on Linux so it can never gain privileges.
* Not yet restricted: reading files (planned: allow-list of model and library
  folders), UDP network traffic on Linux, and any OS-level restriction on
  Windows or macOS beyond file size. See docs/SAFETY_LAYER.md.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys

# Landlock constants (linux/landlock.h).
_SYS_LANDLOCK_CREATE_RULESET = 444
_SYS_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_CREATE_RULESET_VERSION = 1
_PR_SET_NO_NEW_PRIVS = 38

_FS_WRITE_FILE = 1 << 1
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13  # ABI 2
_FS_TRUNCATE = 1 << 14  # ABI 3
_NET_BIND_TCP = 1 << 0  # ABI 4
_NET_CONNECT_TCP = 1 << 1  # ABI 4
_SCOPE_ABSTRACT_UNIX_SOCKET = 1 << 0  # ABI 6
_SCOPE_SIGNAL = 1 << 1  # ABI 6

MARKER = "HFAI-SANDBOX "


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def landlock_abi() -> int:
    """The Landlock version the kernel supports, or 0 if none."""
    if not sys.platform.startswith("linux"):
        return 0
    try:
        version = _libc().syscall(
            _SYS_LANDLOCK_CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION)
        )
    except (OSError, AttributeError):
        return 0
    return max(int(version), 0)


def _apply_landlock(abi: int) -> list[str]:
    libc = _libc()
    fs = (_FS_WRITE_FILE | _FS_REMOVE_DIR | _FS_REMOVE_FILE | _FS_MAKE_CHAR | _FS_MAKE_DIR | _FS_MAKE_REG
          | _FS_MAKE_SOCK | _FS_MAKE_FIFO | _FS_MAKE_BLOCK | _FS_MAKE_SYM)
    applied = ["no file writes", "no file creation or deletion"]
    if abi >= 2:
        fs |= _FS_REFER
    if abi >= 3:
        fs |= _FS_TRUNCATE
        applied.append("no file truncation")
    attr = _RulesetAttr(handled_access_fs=fs)
    size = 8
    if abi >= 4:
        attr.handled_access_net = _NET_BIND_TCP | _NET_CONNECT_TCP
        size = 16
        applied.append("no TCP network connections")
    if abi >= 6:
        attr.scoped = _SCOPE_ABSTRACT_UNIX_SOCKET | _SCOPE_SIGNAL
        size = 24
        applied.append("cannot signal processes outside the sandbox")

    # No rules are added: every handled right is denied everywhere.
    fd = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset failed")
    try:
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(NO_NEW_PRIVS) failed")
        if libc.syscall(_SYS_LANDLOCK_RESTRICT_SELF, ctypes.c_int(fd), ctypes.c_uint32(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self failed")
    finally:
        os.close(fd)
    return applied


def restrict_current_process() -> dict:
    """Apply every restriction this platform supports. Fails loudly, never silently."""
    report = {"platform": sys.platform, "landlock_abi": 0, "applied": [], "not_available": []}

    if os.name == "posix":
        import resource
        import signal

        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)  # writes fail with an error instead of killing
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        report["applied"] += ["maximum file size 0 bytes", "no core dumps"]
    else:
        report["not_available"].append("resource limits (not supported on this OS)")

    abi = landlock_abi()
    report["landlock_abi"] = abi
    if abi > 0:
        report["applied"] += _apply_landlock(abi)
        report["applied"].append("can never gain more privileges (no_new_privs)")
        if abi < 4:
            report["not_available"].append("kernel-level network blocking (needs Landlock ABI 4)")
        if abi < 6:
            report["not_available"].append("signal isolation (needs Landlock ABI 6)")
    else:
        report["not_available"].append("Landlock kernel sandbox (Linux 5.13+ only)")
    report["not_available"] += ["restricting file reads (planned)", "blocking UDP traffic (planned)"]
    return report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--" not in argv or argv.index("--") == len(argv) - 1:
        print("usage: python -m hfai.guardian.sandbox -- <command> [args...]", file=sys.stderr)
        return 2
    command = argv[argv.index("--") + 1:]
    try:
        report = restrict_current_process()
    except OSError as exc:
        # Fail closed: never start the AI process half-restricted.
        print(MARKER + json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        return 3
    print(MARKER + json.dumps(report), file=sys.stderr, flush=True)
    os.execvp(command[0], command)
    return 0  # not reached


if __name__ == "__main__":
    raise SystemExit(main())
