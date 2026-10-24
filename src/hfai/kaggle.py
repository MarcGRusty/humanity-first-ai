"""Everything the Kaggle notebook does, as tested functions (the notebook only calls these).

The notebook (notebooks/kaggle_train.ipynb) runs on Kaggle's free GPUs:

1. check the hardware (two T4s; the P100 is refused, as newer PyTorch no longer supports it);
2. **verify the data sources**: stream a few rows of each and check the field
   names and licence labels match what our adapters expect. The development
   container cannot reach Hugging Face, so this is the first time they are
   checked. It stops if anything is unexpected;
3. download a balanced, openly licensed text mix, cleaned by our filters;
4. train a multilingual tokenizer and measure its language coverage;
5. tokenize everything into training shards;
6. train the model on both GPUs, within a time budget, with checkpoints;
7. write the report card.

``DRY_RUN`` mode does the same steps on the CPU with the small public-domain
book collection instead of Hugging Face, so the whole flow can be tested
anywhere (tests/test_kaggle_flow.py).
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

from hfai.data.filters import Cleaner
from hfai.data.sources import HF_SOURCES, Document, iter_source, normalise_licence

# Languages of Indigenous Peoples are not downloaded by default: under the CARE
# principles their use needs community consent first (DATA.md). This list is a
# starting point that needs community input, not a final judgement.
CONSENT_REQUIRED = {"mi", "haw", "nv", "qu", "iu", "chr", "se", "kl", "oj", "cr", "ay", "gn", "sm", "to", "ty"}

DEFAULT_WIKIPEDIA = {
    "en": 200, "es": 60, "fr": 60, "de": 60, "pt": 60, "it": 40, "nl": 40, "pl": 40, "ru": 60, "uk": 40,
    "zh": 60, "ja": 60, "ko": 60, "ar": 60, "fa": 40, "ur": 40, "hi": 60, "bn": 60, "mr": 30, "ta": 30,
    "te": 30, "tr": 40, "id": 60, "vi": 60, "th": 40, "my": 20, "sw": 30, "ha": 20, "yo": 20, "am": 20,
}  # megabytes of cleaned text per language (smaller Wikipedias simply give what they have)


@dataclass
class RunPlan:
    """What to download and how big a model to train. Edit in the notebook's first cell."""

    common_pile_mb: int = 2400
    common_corpus_mb: int = 300
    wikipedia_mb: dict = field(default_factory=lambda: dict(DEFAULT_WIKIPEDIA))
    tokenizer_sample_mb_per_language: float = 3
    tokenizer_english_sample_mb: float = 20
    vocab_size: int = 32_000
    preset: str = "small"
    batch_size: int = 32
    grad_accum: int = 2
    max_steps: int = 15_000
    max_train_minutes: float = 420.0
    lr: float = 6e-4
    dry_run: bool = False

    def describe(self) -> str:
        total = self.common_pile_mb + self.common_corpus_mb + sum(self.wikipedia_mb.values())
        return (f"About {total / 1000:.1f} GB of text: Common Pile {self.common_pile_mb} MB, Common Corpus "
                f"{self.common_corpus_mb} MB, Wikipedia in {len(self.wikipedia_mb)} languages "
                f"({sum(self.wikipedia_mb.values())} MB). Tokenizer {self.vocab_size:,} tokens; model '{self.preset}'.")


# --- 1. Hardware -------------------------------------------------------------------------


def check_hardware(require_gpu: bool = True) -> dict:
    import torch

    info = {"python": sys.version.split()[0], "torch": torch.__version__, "gpus": []}
    for index in range(torch.cuda.device_count()):
        major, minor = torch.cuda.get_device_capability(index)
        info["gpus"].append({"name": torch.cuda.get_device_name(index), "capability": f"{major}.{minor}"})
        if major < 7:
            raise RuntimeError(
                f"GPU {index} ({torch.cuda.get_device_name(index)}) is too old for current PyTorch. "
                "In the notebook settings, choose Accelerator: 'GPU T4 x2', then run again.")
    if require_gpu and not info["gpus"]:
        raise RuntimeError("No GPU found. In the notebook settings, choose Accelerator: 'GPU T4 x2'.")
    return info


def gpu_smoke_test(work_dir: Path, device: str = "cuda", steps: int = 60) -> dict:
    """Train a tiny model for a few steps on the real device (fp16 on a T4) before the long run.

    Catches GPU-only problems (mixed precision, loss scaling) in a minute, instead of hours in.
    """
    import math
    from array import array

    from hfai.tokenizer import train as train_tokenizer
    from hfai.training.train import TrainConfig, train

    work_dir.mkdir(parents=True, exist_ok=True)
    text = "the river runs to the sea and the sea returns as rain to the hills. " * 400
    tokenizer = train_tokenizer([text], 400)
    tokenizer.save(work_dir / "tok.json")
    ids = array("H", tokenizer.encode(text))
    for name, part in (("train.bin", ids[: len(ids) * 9 // 10]), ("val.bin", ids[len(ids) * 9 // 10:])):
        with open(work_dir / name, "wb") as handle:
            part.tofile(handle)
    shutil.rmtree(work_dir / "run", ignore_errors=True)
    summary = train(TrainConfig(
        data_dir=str(work_dir), tokenizer=str(work_dir / "tok.json"), out_dir=str(work_dir / "run"), preset="tiny",
        model_overrides=dict(d_model=64, n_layers=2, n_heads=2, max_seq_len=64), batch_size=16, lr=3e-3,
        warmup_steps=5, max_steps=steps, eval_every=steps, eval_batches=2, checkpoint_every=steps, log_every=10,
        device=device))
    if not (summary["best_val_loss"] < math.log(tokenizer.vocab_size) - 1):
        raise RuntimeError(f"GPU smoke test: the model did not learn (validation loss {summary['best_val_loss']:.2f})")
    return {"device": summary["device"], "precision": summary["precision"], "val_loss": round(summary["best_val_loss"], 3)}


# --- 2. Verify sources ------------------------------------------------------------------


def verify_sources(rows: int = 3, languages=("en", "sw")) -> list[dict]:
    """Look at a few real rows of each source and check them against our adapters."""
    from datasets import load_dataset

    results = []
    checks = [("common-pile", None), ("common-corpus", None)] + [("wikipedia", lang) for lang in languages]
    for source_id, lang in checks:
        spec = HF_SOURCES[source_id]
        config = spec["config"].format(lang=lang) if spec["config"] else None
        result = {"source": source_id, "config": config, "ok": False, "fields": [], "licence_labels": {}, "problem": ""}
        try:
            stream = load_dataset(spec["dataset"], config, split="train", streaming=True)
            sample = [row for _, row in zip(range(rows), stream)]
            result["fields"] = sorted(sample[0]) if sample else []
            missing = [f for f in (spec["text"], spec["licence_field"]) if f and f not in result["fields"]]
            if missing:
                result["problem"] = f"missing fields {missing}"
            if spec["licence_field"] and not missing:
                labels = Counter(str(row[spec["licence_field"]]) for row in sample)
                result["licence_labels"] = {label: normalise_licence(label) or "NOT RECOGNISED" for label in labels}
            result["ok"] = bool(sample) and not missing
        except Exception as exc:  # report every failure plainly; the notebook stops on any
            result["problem"] = f"{type(exc).__name__}: {exc}"
        results.append(result)
    return results


# --- 3. Download and clean -----------------------------------------------------------------


def _write_until(documents: Iterator[Document], path: Path, megabytes: float, cleaner: Cleaner, stats: Counter) -> None:
    budget = megabytes * 1_000_000
    written = 0
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for doc in documents:
            cleaned, reason = cleaner.clean(doc)
            stats[f"{doc.source}: {reason}"] += 1
            if cleaned is None:
                continue
            handle.write(json.dumps(asdict(cleaned), ensure_ascii=False) + "\n")
            written += len(cleaned.text.encode("utf-8"))
            if written >= budget:
                break
    stats[f"{path.stem}: bytes"] = written


def download_mix(plan: RunPlan, raw_dir: Path, cache_dir: Path) -> dict:
    raw_dir.mkdir(parents=True, exist_ok=True)
    cleaner, stats = Cleaner(), Counter()
    if plan.dry_run:
        _write_until(iter_source("nltk-gutenberg", cache_dir), raw_dir / "en-nltk-gutenberg.jsonl.gz", 50, cleaner, stats)
        _write_until(iter_source("unicode-cldr", cache_dir), raw_dir / "multi-unicode-cldr.jsonl.gz", 5, cleaner, stats)
        return dict(stats)
    from hfai.data.sources import iter_huggingface

    if plan.common_pile_mb:
        _write_until(iter_huggingface("common-pile", shuffle=True), raw_dir / "en-common-pile.jsonl.gz",
                     plan.common_pile_mb, cleaner, stats)
    if plan.common_corpus_mb:
        _write_until(iter_huggingface("common-corpus", shuffle=True), raw_dir / "multi-common-corpus.jsonl.gz",
                     plan.common_corpus_mb, cleaner, stats)
    for lang, megabytes in plan.wikipedia_mb.items():
        if lang in CONSENT_REQUIRED:
            stats[f"wikipedia-{lang}: skipped, community consent needed first"] += 1
            continue
        _write_until(iter_huggingface("wikipedia", language=lang, shuffle=True), raw_dir / f"{lang}-wikipedia.jsonl.gz",
                     megabytes, cleaner, stats)
    return dict(stats)


def iter_downloaded(raw_dir: Path, per_file_mb: float | None = None, english_mb: float | None = None) -> Iterator[Document]:
    """Read the cleaned files back. With limits, take a balanced sample (for tokenizer training)."""
    for path in sorted(raw_dir.glob("*.jsonl.gz")):
        limit = None
        if per_file_mb is not None:
            limit = (english_mb if path.name.startswith("en-") and english_mb else per_file_mb) * 1_000_000
        taken = 0
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                doc = Document(**json.loads(line))
                yield doc
                taken += len(doc.text.encode("utf-8"))
                if limit is not None and taken >= limit:
                    break


# --- 4-7. Tokenizer, shards, training, report ---------------------------------------------------


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def train_tokenizer(plan: RunPlan, raw_dir: Path, out: Path) -> Path:
    from hfai.tokenizer import train

    texts = (d.text for d in iter_downloaded(raw_dir, plan.tokenizer_sample_mb_per_language, plan.tokenizer_english_sample_mb))
    files = sorted(p.name for p in raw_dir.glob("*.jsonl.gz"))
    tokenizer = train(texts, plan.vocab_size, training_info={"sources": files},
                      progress=lambda done, total: print(f"  tokenizer: {done}/{total} merges", flush=True))
    out.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(out)
    return out


def build_shards(raw_dir: Path, tokenizer_path: Path, out_dir: Path, workers: int | None = None) -> dict:
    from hfai.data.pipeline import build
    from hfai.tokenizer import Tokenizer

    return build(iter_downloaded(raw_dir), Tokenizer.load(tokenizer_path), out_dir,
                 val_fraction=0.005, cleaner=Cleaner(), workers=workers or os.cpu_count() or 1)


def train_command(plan: RunPlan, data_dir: Path, tokenizer_path: Path, run_dir: Path, gpus: int) -> list[str]:
    base = ["-m", "hfai.training", "train", "--data", str(data_dir), "--tokenizer", str(tokenizer_path),
            "--out", str(run_dir), "--preset", plan.preset, "--batch-size", str(plan.batch_size),
            "--grad-accum", str(plan.grad_accum), "--max-steps", str(plan.max_steps), "--lr", str(plan.lr),
            "--max-minutes", str(plan.max_train_minutes), "--eval-every", "500", "--checkpoint-every", "500",
            "--warmup-steps", str(min(500, plan.max_steps // 10)), "--log-every", "50"]
    if gpus > 1:
        return [sys.executable, "-m", "torch.distributed.run", f"--nproc_per_node={gpus}", *base]
    return [sys.executable, *base]


def collect_outputs(run_dir: Path, tokenizer_path: Path, coverage: Path, data_dir: Path, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in (run_dir / "report.md", run_dir / "loss.svg", run_dir / "summary.json", run_dir / "metrics.jsonl",
                 run_dir / "compression.json", run_dir / "model.pt", tokenizer_path, coverage, data_dir / "report.json"):
        if path.exists():
            target = out / (f"data-{path.name}" if path.parent == data_dir else path.name)
            shutil.copy2(path, target)
            copied.append(target.name)
    return copied
