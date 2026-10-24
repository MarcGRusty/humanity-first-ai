"""Command line for the data pipeline.

    python -m hfai.data build --sources nltk-gutenberg --tokenizer tokenizer.json --out data/tokenized/proof
    python -m hfai.data sources        # list sources and their status
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hfai.data.pipeline import build
from hfai.data.sources import iter_source, load_sources
from hfai.tokenizer import Tokenizer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hfai.data")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="clean, tokenize and shard documents")
    b.add_argument("--sources", required=True)
    b.add_argument("--tokenizer", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--cache", type=Path, default=Path("data/raw"))
    b.add_argument("--val-fraction", type=float, default=0.02)
    sub.add_parser("sources", help="list data sources")
    args = parser.parse_args(argv)

    if args.command == "sources":
        for source in load_sources().values():
            print(f"{source['id']:<28} {source['status']:<10} {source['licence']:<20} verified={source['verified']}")
        return 0

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    def documents():
        for source in sources:
            yield from iter_source(source, args.cache)

    report = build(documents(), Tokenizer.load(args.tokenizer), args.out, val_fraction=args.val_fraction)
    print(json.dumps(report["totals"], indent=2))
    for source, info in report["sources"].items():
        print(f"{source}: {info['kept_and_dropped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
