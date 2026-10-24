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
  renaming or truncating any file (ABI 3+ for truncation), except inside one
  private scratch folder the guardian creates for it, wipes on every start and
  stop, and never reads (some libraries, such as PyTorch, refuse to load
  without a usable temporary folder); each file there is capped at 64 MB.
  No TCP connections or listening (ABI 4+); no sending signals to processes
  outside the sandbox, so it cannot signal the guardian (ABI 6+).
* Without Landlock (macOS and older Linux): maximum file size 0 bytes, so
  writes fail everywhere. Also no core dumps, and ``no_new_privs`` on Linux so
  it can never gain privileges.
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
_SYS_LANDLOCK_ADD_RULE = 445
_SYS_LANDLOCK_RESTRICT_SELF = 446
_LANDLOCK_RULE_PATH_BENEATH = 1
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
SCRATCH_FILE_LIMIT = 64 * 1024 * 1024


class _RulesetAttr(ctypes.Structure):
    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


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


def _apply_landlock(abi: int, scratch: str | None = None) -> list[str]:
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

    fd = libc.syscall(_SYS_LANDLOCK_CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if fd < 0:
        raise OSError(ctypes.get_errno(), "landlock_create_ruleset failed")
    try:
        # Every handled right is denied everywhere, except ordinary file work inside the scratch folder.
        if scratch is not None:
            allowed = _FS_WRITE_FILE | _FS_REMOVE_FILE | _FS_REMOVE_DIR | _FS_MAKE_REG | _FS_MAKE_DIR
            if abi >= 3:
                allowed |= _FS_TRUNCATE
            parent = os.open(scratch, os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                rule = _PathBeneathAttr(allowed_access=allowed, parent_fd=parent)
                if libc.syscall(_SYS_LANDLOCK_ADD_RULE, ctypes.c_int(fd), ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
                                ctypes.byref(rule), ctypes.c_uint32(0)) != 0:
                    raise OSError(ctypes.get_errno(), "landlock_add_rule failed")
            finally:
                os.close(parent)
            applied[:] = [item + " outside its private scratch folder" if item.startswith("no file") else item
                          for item in applied]
        if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "prctl(NO_NEW_PRIVS) failed")
        if libc.syscall(_SYS_LANDLOCK_RESTRICT_SELF, ctypes.c_int(fd), ctypes.c_uint32(0)) != 0:
            raise OSError(ctypes.get_errno(), "landlock_restrict_self failed")
    finally:
        os.close(fd)
    return applied


def restrict_current_process(scratch: str | None = None) -> dict:
    """Apply every restriction this platform supports. Fails loudly, never silently.

    ``scratch`` is honoured only where Landlock can confine writes to it;
    elsewhere no file writes are allowed at all.
    """
    report = {"platform": sys.platform, "landlock_abi": 0, "applied": [], "not_available": []}
    abi = landlock_abi()
    use_scratch = scratch is not None and abi > 0

    if os.name == "posix":
        import resource
        import signal

        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)  # writes fail with an error instead of killing
        limit = SCRATCH_FILE_LIMIT if use_scratch else 0
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        report["applied"] += [f"maximum file size {limit // (1024 * 1024)} MB" if limit else "maximum file size 0 bytes",
                              "no core dumps"]
    else:
        report["not_available"].append("resource limits (not supported on this OS)")

    report["landlock_abi"] = abi
    if abi > 0:
        report["applied"] += _apply_landlock(abi, scratch if use_scratch else None)
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
        print("usage: python -m hfai.guardian.sandbox [--scratch DIR] -- <command> [args...]", file=sys.stderr)
        return 2
    options, command = argv[:argv.index("--")], argv[argv.index("--") + 1:]
    scratch = options[options.index("--scratch") + 1] if "--scratch" in options else None
    try:
        report = restrict_current_process(scratch)
    except OSError as exc:
        # Fail closed: never start the AI process half-restricted.
        print(MARKER + json.dumps({"error": str(exc)}), file=sys.stderr, flush=True)
        return 3
    print(MARKER + json.dumps(report), file=sys.stderr, flush=True)
    os.execvp(command[0], command)
    return 0  # not reached


if __name__ == "__main__":
    raise SystemExit(main())
