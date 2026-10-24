"""Command line for the safety layer.

    python -m hfai.guardian demo [--save FILE]   run the safety-layer demonstration
    python -m hfai.guardian stop [--reason TEXT] kill switch: stop the AI process now
    python -m hfai.guardian release              allow the AI to start again (people only)
    python -m hfai.guardian status               is the kill switch engaged? is the log intact?
    python -m hfai.guardian log                  show the audit log
    python -m hfai.guardian verify-log [--expected-head HASH]
    python -m hfai.guardian integrity [--update] check (or, maintainers: record) protected files
    python -m hfai.guardian rules                show the action rules in plain language

The data folder defaults to ~/.hfai, or set HFAI_DATA_DIR.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from hfai.charter import REPO_ROOT, load_charter
from hfai.guardian import integrity
from hfai.guardian.actions import ACTION_SCHEMA
from hfai.guardian.audit import AuditLog, format_entry, verify_file
from hfai.guardian.core import DEFAULT_RULES
from hfai.guardian.killswitch import KillSwitch, stop_from_outside
from hfai.rules import describe, parse_rules


def default_data_dir() -> Path:
    return Path(os.environ.get("HFAI_DATA_DIR", Path.home() / ".hfai"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hfai.guardian", description="The safety layer's controls.")
    parser.add_argument("--data-dir", type=Path, default=None, help="data folder (default ~/.hfai or HFAI_DATA_DIR)")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="run the safety-layer demonstration")
    demo.add_argument("--save", type=Path, help="also save the transcript to this file")
    stop = sub.add_parser("stop", help="kill switch: stop the AI process now")
    stop.add_argument("--reason", default="stop command")
    sub.add_parser("release", help="allow the AI process to start again")
    sub.add_parser("status", help="kill switch and audit log status")
    sub.add_parser("log", help="show the audit log")
    verify = sub.add_parser("verify-log", help="check the audit log for tampering")
    verify.add_argument("--expected-head", help="the latest fingerprint you saved earlier")
    check = sub.add_parser("integrity", help="check protected files against the manifest")
    check.add_argument("--update", action="store_true", help="maintainers only: record current fingerprints")
    sub.add_parser("rules", help="show the action rules in plain language")
    args = parser.parse_args(argv)
    data_dir = args.data_dir or default_data_dir()

    if args.command == "demo":
        from hfai.guardian.demo import run_demo

        run_demo(args.save)
        return 0
    if args.command == "stop":
        print(stop_from_outside(data_dir, args.reason))
        return 0
    if args.command == "release":
        audit = AuditLog(data_dir / "audit.log")
        switch = KillSwitch(data_dir, audit)
        if not switch.engaged:
            print("The kill switch is not engaged.")
            return 0
        switch.release(by="human (command line)")
        print("Kill switch released. The AI process may be started again.")
        return 0
    if args.command == "status":
        switch = KillSwitch(data_dir)
        print(f"Data folder: {data_dir}")
        print("Kill switch: ENGAGED, the AI cannot run." if switch.engaged else "Kill switch: not engaged.")
        print(verify_file(data_dir / "audit.log").explain())
        return 0
    if args.command == "log":
        path = data_dir / "audit.log"
        if not path.exists():
            print("No audit log yet.")
            return 0
        for entry in AuditLog(path).entries():
            print(format_entry(entry))
        return 0
    if args.command == "verify-log":
        result = verify_file(data_dir / "audit.log", args.expected_head)
        print(result.explain())
        return 0 if result.ok else 1
    if args.command == "integrity":
        if args.update:
            path = integrity.write_manifest(REPO_ROOT)
            print(f"Recorded fingerprints of {len(integrity.protected_files(REPO_ROOT))} protected files in {path}.")
            print("This is a protected change: it must be reviewed and approved by a human maintainer.")
            return 0
        report = integrity.check(REPO_ROOT)
        print(report.explain())
        return 0 if report.ok else 1
    if args.command == "rules":
        charter = load_charter()
        ids = {item.id for group in (charter.values, charter.hard_limits) for item in group}
        rules = parse_rules((REPO_ROOT / DEFAULT_RULES).read_text(encoding="utf-8"), ACTION_SCHEMA, ids)
        print("What the AI may propose (everything still needs your consent):")
        print(describe(rules))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
