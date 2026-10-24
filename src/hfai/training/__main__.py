"""Command line for training.

    python -m hfai.training train --data DIR --tokenizer FILE --out DIR [--preset tiny] [--max-steps N] ...
    python -m hfai.training report --run DIR --tokenizer FILE [--data DIR] [--title TEXT]
    python -m hfai.training generate --run DIR --tokenizer FILE --prompt TEXT

For several GPUs: torchrun --nproc_per_node=2 -m hfai.training train ...
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hfai.training")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", required=True)
    t.add_argument("--tokenizer", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--preset", default="tiny")
    t.add_argument("--model", default="{}", help='JSON overrides, e.g. \'{"n_layers": 6}\'')
    for name, kind, default in (("batch-size", int, 16), ("grad-accum", int, 1), ("lr", float, 1e-3),
                                ("warmup-steps", int, 100), ("max-steps", int, 1000), ("eval-every", int, 200),
                                ("eval-batches", int, 20), ("checkpoint-every", int, 200), ("log-every", int, 10),
                                ("max-minutes", float, None), ("stop-at-step", int, None), ("assumed-watts", float, None),
                                ("seed", int, 1337)):
        t.add_argument(f"--{name}", type=kind, default=default)
    t.add_argument("--device", default="auto")
    r = sub.add_parser("report")
    r.add_argument("--run", required=True, type=Path)
    r.add_argument("--tokenizer", required=True, type=Path)
    r.add_argument("--data", type=Path)
    r.add_argument("--title", default="Training run")
    g = sub.add_parser("generate")
    g.add_argument("--run", required=True, type=Path)
    g.add_argument("--tokenizer", required=True, type=Path)
    g.add_argument("--prompt", required=True)
    g.add_argument("--tokens", type=int, default=60)
    args = parser.parse_args(argv)

    if args.command == "train":
        from hfai.training.train import TrainConfig, train

        config = TrainConfig(
            data_dir=args.data, tokenizer=args.tokenizer, out_dir=args.out, preset=args.preset,
            model_overrides=json.loads(args.model), batch_size=args.batch_size, grad_accum=args.grad_accum,
            lr=args.lr, warmup_steps=args.warmup_steps, max_steps=args.max_steps, eval_every=args.eval_every,
            eval_batches=args.eval_batches, checkpoint_every=args.checkpoint_every, log_every=args.log_every,
            max_minutes=args.max_minutes, stop_at_step=args.stop_at_step, assumed_watts=args.assumed_watts,
            seed=args.seed, device=args.device,
        )
        summary = train(config)
        if summary:
            print(json.dumps(summary, indent=2))
        return 0
    if args.command == "report":
        from hfai.training.report import write_report

        print(f"Report written to {write_report(args.run, args.tokenizer, args.data, args.title)}")
        return 0
    if args.command == "generate":
        from hfai.tokenizer import Tokenizer
        from hfai.training.report import samples

        for prompt, text in samples(args.run, Tokenizer.load(args.tokenizer), (args.prompt,), args.tokens):
            print(f"[AI-generated] {prompt}{text}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
