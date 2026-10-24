"""The report card for a training run, written for people, not just engineers."""

from __future__ import annotations

import json
import lzma
import math
import zlib
from pathlib import Path

import numpy as np
import torch

from hfai.tokenizer import Tokenizer
from hfai.training.chart import line_chart
from hfai.training.checkpoint import load_model
from hfai.training.train import SAMPLE_PROMPTS


def _read_metrics(run: Path) -> tuple[list[dict], list[dict]]:
    train, evals = [], []
    path = run / "metrics.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            (evals if "val_loss" in record else train).append(record)
    return train, evals


def samples(run: Path, tokenizer: Tokenizer, prompts=SAMPLE_PROMPTS, tokens: int = 60, seed: int = 0) -> list[tuple[str, str]]:
    model, _ = load_model(run / "model.pt")
    model.eval()
    out = []
    for index, prompt in enumerate(prompts):
        generator = torch.Generator().manual_seed(seed + index)
        idx = torch.tensor([tokenizer.encode(prompt)], dtype=torch.long)
        result = model.generate(idx, tokens, temperature=0.8, top_k=50,
                                stop_token=tokenizer.token_id("<|endoftext|>"), generator=generator)
        out.append((prompt, tokenizer.decode(result[0, idx.shape[1]:].tolist())))
    return out


@torch.no_grad()
def compare_with_compressors(run: Path, tokenizer: Tokenizer, data_dir: Path) -> dict:
    """Bits per byte on the *whole* validation text: this model vs. standard compressors.

    The compressors see only the validation text itself, while the model first
    learned from the training text, so this is a reference point, not a fair contest.
    """
    model, _ = load_model(run / "model.pt")
    model.eval()
    tokens = np.fromfile(Path(data_dir) / "val.bin", dtype="<u2").astype(np.int64)
    eot = tokenizer.token_id("<|endoftext|>")
    text_bytes = tokenizer.decode_bytes(t for t in tokens.tolist() if t != eot)
    lengths = torch.tensor([len(piece) for piece in tokenizer.vocab] + [0] * len(tokenizer.special), dtype=torch.float64)

    window = model.config.max_seq_len
    nats, counted_bytes = 0.0, 0.0
    for start in range(0, len(tokens) - 1, window):
        chunk = torch.from_numpy(tokens[start:start + window + 1])
        if len(chunk) < 2:
            break
        x, y = chunk[:-1][None], chunk[1:][None]
        logits, _ = model(x)
        nats += torch.nn.functional.cross_entropy(logits[0].float(), y[0], reduction="sum").item()
        counted_bytes += lengths[y[0]].sum().item()
    uniform = math.log(tokenizer.vocab_size) * (len(tokens) - 1) / math.log(2) / counted_bytes
    return {
        "bytes": len(text_bytes),
        "model": nats / math.log(2) / counted_bytes,
        "random_guessing": uniform,
        "gzip -9": 8 * len(zlib.compress(text_bytes, 9)) / len(text_bytes),
        "xz -9e": 8 * len(lzma.compress(text_bytes, preset=9 | lzma.PRESET_EXTREME)) / len(text_bytes),
    }


def write_report(run: Path, tokenizer_path: Path, data_dir: Path | None = None, title: str = "Training run") -> Path:
    run = Path(run)
    tokenizer = Tokenizer.load(tokenizer_path)
    summary = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    train, evals = _read_metrics(run)
    data_report = {}
    if data_dir is not None and (Path(data_dir) / "report.json").exists():
        data_report = json.loads((Path(data_dir) / "report.json").read_text(encoding="utf-8"))

    chart = line_chart(
        {"training loss": [(r["tokens"], r["loss"]) for r in train],
         "validation loss": [(e["tokens"], e["val_loss"]) for e in _attach_tokens(evals, train)]},
        "Loss: lower means better predictions", "tokens seen", "loss (nats per token)")
    (run / "loss.svg").write_text(chart, encoding="utf-8")

    best = min(evals, key=lambda e: e["val_loss"]) if evals else None
    first = evals[0] if evals else None
    uniform = math.log(tokenizer.vocab_size)
    hours = summary["elapsed_s"] / 3600
    lines = [
        f"# {title}: report card",
        "",
        "## In plain language",
        "",
        f"A language model with **{summary['parameters'] / 1e6:.1f} million parameters** was trained from scratch "
        f"on **{summary['tokens_seen']:,} tokens** of openly licensed text, in **{_duration(summary['elapsed_s'])}** "
        f"on `{summary['device']}`" + (f" ({summary['world_size']} processes)" if summary['world_size'] > 1 else "") + ".",
        "",
    ]
    if best:
        lines += [
            f"- Before training, a model guessing at random would score a loss of about **{uniform:.2f}**.",
            f"- After training, its best score on text it never trained on was **{best['val_loss']:.2f}** "
            f"(perplexity {best['val_perplexity']:.0f}: roughly, it narrows each next-token guess down to about "
            f"{best['val_perplexity']:.0f} likely options out of {tokenizer.vocab_size:,}).",
            f"- **The falling line in the chart is the evidence that it learned.**" if first and best["val_loss"] < first["val_loss"] else
            "- **Validation loss did not improve: something is wrong; see the metrics.**",
            "",
        ]
    if data_dir is not None and (run / "model.pt").exists():
        comparison = compare_with_compressors(run, tokenizer, Path(data_dir))
        (run / "compression.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
        lines += [
            f"How well does it predict text? One honest yardstick is compression: a model that predicts text well "
            f"can store it in fewer bits. On the whole validation text ({comparison['bytes']:,} bytes, never trained on):",
            "",
            "| Method | Bits per byte (lower is better) |",
            "|---|---|",
            f"| Random guessing, with our tokenizer | {comparison['random_guessing']:.2f} |",
            f"| gzip (maximum compression) | {comparison['gzip -9']:.2f} |",
            f"| xz (maximum compression) | {comparison['xz -9e']:.2f} |",
            f"| **This model** | **{comparison['model']:.2f}** |",
            "",
            "Caveat: the compressors only see the validation text itself, while the model first learned from "
            "similar books, so this is a reference point, not a fair contest.",
            "",
        ]
    lines += [
        "![Loss chart](loss.svg)",
        "",
        "## What it can and cannot do (honestly)",
        "",
        "It continues text in the style of what it read, word by word. It does not understand, reason, "
        "or know facts reliably, and it will make things up. It is a step that proves our tokenizer, "
        "model and training code work end to end; usefulness comes from larger models and from the cited "
        "library search (model option C).",
        "",
        "## Sample text (AI-generated by this model; may be nonsense or wrong)",
        "",
    ]
    if (run / "model.pt").exists():
        for prompt, continuation in samples(run, tokenizer):
            lines += [f"> **{prompt}**{continuation}", ""]
    lines += [
        "## Cost",
        "",
        f"- Time: {_duration(summary['elapsed_s'])} ({hours:.2f} hours)",
        f"- Energy: {summary['watt_hours'] / 1000:.4f} kWh, {summary['energy_method']}",
        f"- Device: `{summary['device']}`, precision {summary['precision']}",
        "",
        "## Details",
        "",
        f"- Stopped because: {summary['stop_reason']} (step {summary['step']} of {summary['max_steps']})",
        f"- Model: `{json.dumps(summary['model_config'])}`",
        f"- Tokenizer fingerprint: `{summary['tokenizer_fingerprint'][:16]}` (vocabulary {tokenizer.vocab_size:,})",
    ]
    if data_report:
        lines.append(f"- Data: {data_report['totals']['train_tokens']:,} training tokens, "
                     f"{data_report['totals']['val_tokens']:,} validation tokens")
        for source, info in data_report["sources"].items():
            lines.append(f"  - `{source}`: licences {info['licences']}, kept/dropped {info['kept_and_dropped']}")
    if best:
        lines.append(f"- Best validation: step {best['step']}, loss {best['val_loss']:.4f}, "
                     f"perplexity {best['val_perplexity']:.1f}, bits/byte {best['val_bits_per_byte']:.4f}")
    lines.append("")
    path = run / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _attach_tokens(evals: list[dict], train: list[dict]) -> list[dict]:
    tokens_at = {r["step"]: r["tokens"] for r in train}
    return [{**e, "tokens": tokens_at.get(e["step"], 0)} for e in evals if e["step"] in tokens_at]


def _duration(seconds: float) -> str:
    minutes = seconds / 60
    return f"{minutes:.1f} minutes" if minutes < 120 else f"{minutes / 60:.1f} hours"
