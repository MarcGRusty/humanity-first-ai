"""Command line for the tokenizer.

    python -m hfai.tokenizer train --sources nltk-gutenberg,unicode-cldr --vocab 8192 --out tokenizer.json
    python -m hfai.tokenizer report tokenizer.json [--out docs/coverage/tokenizer.md] [--title NAME]
    python -m hfai.tokenizer encode tokenizer.json "some text"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from hfai.tokenizer.bpe import Tokenizer, train


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hfai.tokenizer")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train", help="train a tokenizer from listed sources")
    t.add_argument("--sources", required=True, help="comma-separated source IDs from data/sources.toml")
    t.add_argument("--vocab", type=int, required=True)
    t.add_argument("--out", type=Path, required=True)
    t.add_argument("--cache", type=Path, default=Path("data/raw"))
    r = sub.add_parser("report", help="measure language coverage")
    r.add_argument("tokenizer", type=Path)
    r.add_argument("--out", type=Path)
    r.add_argument("--title", default="")
    e = sub.add_parser("encode", help="show how a text is split into tokens")
    e.add_argument("tokenizer", type=Path)
    e.add_argument("text")
    args = parser.parse_args(argv)

    if args.command == "train":
        from hfai.data.filters import Cleaner
        from hfai.data.sources import iter_source

        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        cleaner = Cleaner()

        def texts():
            for source in sources:
                for doc in iter_source(source, args.cache):
                    cleaned, _ = cleaner.clean(doc)
                    if cleaned is not None:
                        yield cleaned.text

        began = time.time()
        tokenizer = train(texts(), args.vocab, training_info={"sources": sources},
                          progress=lambda done, total: print(f"  {done}/{total} merges", file=sys.stderr))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        tokenizer.save(args.out)
        info = tokenizer.meta["training"]
        print(f"Trained on {info['bytes']:,} bytes in {time.time() - began:.1f} s: "
              f"{info['merges_learned']} merges, vocabulary {tokenizer.vocab_size}. Saved to {args.out}")
        return 0

    tokenizer = Tokenizer.load(args.tokenizer)
    if args.command == "report":
        from hfai.tokenizer.report import markdown, measure

        results = measure(tokenizer)
        text = markdown(results, args.title or args.tokenizer.stem, tokenizer)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text, encoding="utf-8")
        passed = sum(r.round_trip for r in results)
        print(f"Round trip: {passed}/{len(results)} languages." + (f" Report: {args.out}" if args.out else ""))
        return 0 if passed == len(results) else 1
    if args.command == "encode":
        ids = tokenizer.encode(args.text)
        pieces = [tokenizer.decode_bytes([i]).decode("utf-8", errors="replace") for i in ids]
        print(f"{len(ids)} tokens: {pieces}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
