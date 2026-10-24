"""MOCK AI process. It stands in for the real model until milestone M3.

It does not think, understand or generate anything. It replays scripted replies
so the safety layer can be tested and demonstrated end to end, including with
replies a misbehaving model might give (proposing forbidden actions, obeying
injected instructions, hanging, trying to write files or use the network).

Usage: python -m hfai.worker.mock MODE [ARG]

Modes:
  echo                  reply "MOCK echo: <message>" with no proposals
  scripted PATH         reply with entries from a JSON list, in order, then echo
  hang                  never reply (to test timeouts and the kill switch)
  ignore_sigterm        ignore polite stop signals, then never reply
  try_write PATH        try to write and truncate PATH, report what happened
  try_network PORT      try to connect to 127.0.0.1:PORT, report what happened
  try_signal PID        try to send a stop signal to process PID, report what happened
  garbage               reply with text that breaks the protocol
"""

from __future__ import annotations

import json
import os
import signal
import socket
import sys
import time

from hfai.worker.protocol import encode, install_network_guard, parse_request


def _attempt(action) -> str:
    try:
        action()
        return "SUCCEEDED"
    except Exception as exc:  # report any failure; this is a test probe
        return f"BLOCKED ({type(exc).__name__}: {exc})"


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "echo"
    arg = argv[1] if len(argv) > 1 else ""
    script: list[dict] = []
    if mode == "scripted":
        with open(arg, encoding="utf-8") as handle:
            script = json.load(handle)
    if mode == "ignore_sigterm" and os.name == "posix":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if mode != "try_network":
        install_network_guard()

    for line in sys.stdin:
        request = parse_request(line)
        if request["type"] == "shutdown":
            return 0
        message = request["message"]
        text, proposals = f"MOCK echo: {message}", []

        if mode in ("hang", "ignore_sigterm"):
            while True:
                time.sleep(3600)
        elif mode == "garbage":
            sys.stdout.write("this is not the protocol\n")
            sys.stdout.flush()
            continue
        elif mode == "scripted" and script:
            entry = script.pop(0)
            text, proposals = entry.get("text", ""), entry.get("proposals", [])
        elif mode == "try_write":
            def write():
                with open(arg, "w", encoding="utf-8") as handle:
                    handle.write("overwritten by the AI process")
            def truncate():
                os.truncate(arg, 0)
            text = f"write: {_attempt(write)}; truncate: {_attempt(truncate)}"
        elif mode == "try_network":
            def connect():
                with socket.create_connection(("127.0.0.1", int(arg)), timeout=2):
                    pass
            text = f"network: {_attempt(connect)}"
        elif mode == "try_signal":
            text = f"signal: {_attempt(lambda: os.kill(int(arg), signal.SIGTERM))}"

        sys.stdout.write(encode({"id": request["id"], "text": text, "proposals": proposals}))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
