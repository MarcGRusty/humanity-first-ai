"""The Kaggle notebook's whole flow, in dry-run mode on the CPU, plus checks on the notebook file."""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from hfai.data.sources import Document
from hfai.data.sources import iter_source as real_iter_source

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "kaggle_train.ipynb"


def test_notebook_is_valid_and_only_calls_real_functions():
    from hfai import kaggle

    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    code = ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]
    for source in code:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "hfai.kaggle":
                for alias in node.names:
                    assert hasattr(kaggle, alias.name), alias.name
    assert "DRY_RUN = False" in code[0]


def test_notebook_is_up_to_date_with_its_generator():
    sys.path.insert(0, str(ROOT / "notebooks"))
    try:
        import build_notebook
    finally:
        sys.path.pop(0)
    assert json.loads(NOTEBOOK.read_text(encoding="utf-8")) == build_notebook.build()


def test_p100_style_old_gpus_are_refused(monkeypatch):
    torch = pytest.importorskip("torch")
    from hfai import kaggle

    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(torch.cuda, "get_device_capability", lambda i: (6, 0))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda i: "Tesla P100")
    with pytest.raises(RuntimeError, match="T4 x2"):
        kaggle.check_hardware()


def test_gpu_smoke_test_runs_on_cpu_too(tmp_path):
    pytest.importorskip("torch")
    from hfai import kaggle

    result = kaggle.gpu_smoke_test(tmp_path, device="cpu", steps=40)
    assert result["device"] == "cpu" and result["val_loss"] < 4


def test_indigenous_languages_need_consent_and_are_skipped(tmp_path, monkeypatch):
    from hfai import kaggle

    calls = []
    monkeypatch.setattr("hfai.data.sources.iter_huggingface", lambda *a, **k: calls.append((a, k)) or iter(()))
    plan = kaggle.RunPlan(common_pile_mb=0, common_corpus_mb=0, wikipedia_mb={"mi": 5, "sw": 5})
    stats = kaggle.download_mix(plan, tmp_path / "raw", tmp_path / "cache")
    assert any("mi" in key and "consent" in key for key in stats)
    assert all(k.get("language") != "mi" for _, k in calls)


def test_dry_run_flow_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("babel")
    from hfai import kaggle

    def books(source_id, cache_dir, **kwargs):
        # Stand-in for the downloaded public-domain books, so the test needs no network.
        if source_id == "nltk-gutenberg":
            for i in range(60):
                text = f"Chapter {i}. The river ran past the old mill, and the children watched the boats go by. " * 30
                yield Document("nltk-gutenberg", f"book#{i}", text, "public-domain", "en")
        else:
            yield from real_iter_source(source_id, cache_dir, **kwargs)

    monkeypatch.setattr(kaggle, "iter_source", books)
    plan = kaggle.RunPlan(dry_run=True, vocab_size=600, preset="tiny", batch_size=4, grad_accum=1, max_steps=20,
                          max_train_minutes=3, lr=3e-3, tokenizer_sample_mb_per_language=0.05, tokenizer_english_sample_mb=0.2)
    raw, data, run = tmp_path / "raw", tmp_path / "data", tmp_path / "run"
    stats = kaggle.download_mix(plan, raw, tmp_path / "cache")
    assert stats["nltk-gutenberg: kept"] > 0 and stats["unicode-cldr: kept"] > 200

    tokenizer = kaggle.train_tokenizer(plan, raw, tmp_path / "tokenizer.json")
    report = kaggle.build_shards(raw, tokenizer, data, workers=2)
    assert report["totals"]["train_tokens"] > 1000

    command = kaggle.train_command(plan, data, tokenizer, run, gpus=1)
    command += ["--model", json.dumps({"d_model": 32, "n_layers": 2, "n_heads": 2, "max_seq_len": 32}), "--device", "cpu"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    subprocess.run(command, check=True, env=env, capture_output=True)
    subprocess.run([sys.executable, "-m", "hfai.training", "report", "--run", str(run), "--tokenizer", str(tokenizer),
                    "--data", str(data)], check=True, env=env, capture_output=True)
    coverage = tmp_path / "coverage.md"
    coverage.write_text("coverage", encoding="utf-8")
    copied = kaggle.collect_outputs(run, tokenizer, coverage, data, tmp_path / "outputs")
    for name in ("report.md", "loss.svg", "summary.json", "model.pt", "tokenizer.json", "data-report.json"):
        assert name in copied
