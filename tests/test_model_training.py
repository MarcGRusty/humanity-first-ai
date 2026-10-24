"""The model, training loop, checkpoints and evaluation must work and be honest."""

import json
import math
import os
import subprocess
import sys
from array import array
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from hfai.evals.lm import evaluate, token_byte_lengths  # noqa: E402
from hfai.model import ModelConfig, Transformer, build_model  # noqa: E402
from hfai.model.transformer import apply_rope, rope_tables  # noqa: E402
from hfai.tokenizer import train as train_tokenizer  # noqa: E402
from hfai.training.checkpoint import load_model, load_safe, save_weights  # noqa: E402
from hfai.training.data import TokenData  # noqa: E402
from hfai.training.train import TrainConfig, lr_at, train  # noqa: E402

TINY = dict(d_model=32, n_layers=2, n_heads=2, max_seq_len=32)


def tiny_model(vocab=64, **kw):
    torch.manual_seed(0)
    return Transformer(ModelConfig(vocab_size=vocab, **{**TINY, **kw}))


def test_shapes_and_finite_loss():
    model = tiny_model()
    x = torch.randint(0, 64, (3, 16))
    y = torch.randint(0, 64, (3, 16))  # independent targets: nothing to learn from the input
    logits, loss = model(x, y)
    assert logits.shape == (3, 16, 64)
    assert torch.isfinite(loss)
    assert abs(loss.item() - math.log(64)) < 0.5  # untrained: close to random guessing


def test_causal_future_tokens_do_not_leak():
    model = tiny_model().eval()
    x = torch.randint(0, 64, (1, 16))
    changed = x.clone()
    changed[0, 10:] = (changed[0, 10:] + 1) % 64
    a, _ = model(x)
    b, _ = model(changed)
    assert torch.allclose(a[0, :10], b[0, :10], atol=1e-5)
    assert not torch.allclose(a[0, 10:], b[0, 10:])


def test_rope_preserves_length():
    cos, sin = rope_tables(8, 16, 10_000.0)
    x = torch.randn(1, 1, 16, 8)
    assert torch.allclose(apply_rope(x, cos, sin).norm(dim=-1), x.norm(dim=-1), atol=1e-5)


def test_presets_match_documented_sizes():
    assert 24e6 < build_model(32000, "small").num_parameters() < 28e6
    assert 100e6 < build_model(32000, "medium").num_parameters() < 115e6


def test_rejects_too_long_input():
    with pytest.raises(ValueError):
        tiny_model()(torch.zeros(1, 33, dtype=torch.long))


def test_it_learns_a_pattern():
    """The basic promise: training makes predictions better."""
    model = tiny_model()
    opt = torch.optim.AdamW(model.parameters(), lr=3e-3)
    pattern = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8] * 4])
    _, before = model(pattern[:, :-1], pattern[:, 1:])
    for _ in range(150):
        _, loss = model(pattern[:, :-1], pattern[:, 1:])
        opt.zero_grad()
        loss.backward()
        opt.step()
    assert loss.item() < 0.1 < before.item()


def test_generation_is_reproducible_and_stops():
    model = tiny_model().eval()
    prompt = torch.tensor([[1, 2, 3]])
    a = model.generate(prompt, 10, generator=torch.Generator().manual_seed(1))
    b = model.generate(prompt, 10, generator=torch.Generator().manual_seed(1))
    assert torch.equal(a, b) and a.shape[1] == 13
    greedy = model.generate(prompt, 10, temperature=0)
    first = int(greedy[0, 3])
    assert model.generate(prompt, 10, temperature=0, stop_token=first).shape[1] == 4


def test_lr_schedule():
    config = TrainConfig(data_dir="", tokenizer="", out_dir="", lr=1.0, warmup_steps=10, max_steps=110, min_lr_ratio=0.1)
    assert lr_at(0, config) == pytest.approx(0.1)
    assert lr_at(9, config) == pytest.approx(1.0)
    assert lr_at(110, config) == pytest.approx(0.1)
    assert lr_at(60, config) == pytest.approx(0.55)


def test_bits_per_byte_of_a_random_guesser():
    tok = train_tokenizer(["abc " * 100], 300)
    lengths = token_byte_lengths(tok)
    model = Transformer(ModelConfig(vocab_size=tok.vocab_size, **TINY))
    torch.nn.init.zeros_(model.head.weight)  # all logits equal: a uniform guesser (head is tied, so embeddings too)
    ids = torch.tensor([tok.encode("abc " * 20)[:33]])
    result = evaluate(model, [(ids[:, :-1], ids[:, 1:])], lengths, torch.device("cpu"))
    assert result["val_loss"] == pytest.approx(math.log(tok.vocab_size), rel=1e-4)
    targets = ids[0, 1:]
    expected_bpb = math.log2(tok.vocab_size) * len(targets) / lengths[targets].sum().item()
    assert result["val_bits_per_byte"] == pytest.approx(expected_bpb, rel=1e-4)


def test_weights_round_trip_and_safe_loading(tmp_path):
    model = tiny_model()
    save_weights(model, model.config.to_dict(), "abc", tmp_path / "model.pt")
    loaded, meta = load_model(tmp_path / "model.pt")
    x = torch.randint(0, 64, (1, 8))
    assert torch.allclose(model(x)[0], loaded(x)[0])
    assert meta["tokenizer_fingerprint"] == "abc"


def test_loading_refuses_hidden_code(tmp_path):
    class Evil:
        def __reduce__(self):
            return (os.system, ("echo pwned",))

    torch.save({"format": "hfai-weights", "payload": Evil()}, tmp_path / "evil.pt")
    with pytest.raises(Exception):
        load_safe(tmp_path / "evil.pt")


# --- the full training loop -------------------------------------------------------


@pytest.fixture(scope="module")
def tiny_dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    text = "the cat sat on the mat and the dog sat on the log. " * 400
    tok = train_tokenizer([text], 320)
    tok.save(root / "tok.json")
    ids = array("H", tok.encode(text))
    for name, part in (("train.bin", ids[: len(ids) * 9 // 10]), ("val.bin", ids[len(ids) * 9 // 10:])):
        with open(root / name, "wb") as handle:
            part.tofile(handle)
    (root / "report.json").write_text(json.dumps({"totals": {"train_tokens": 1, "val_tokens": 1}, "sources": {}}))
    return root


def run_config(data: Path, out: Path, **kw) -> TrainConfig:
    base = dict(data_dir=str(data), tokenizer=str(data / "tok.json"), out_dir=str(out), preset="tiny",
                model_overrides=dict(d_model=32, n_layers=2, n_heads=2, max_seq_len=32), batch_size=8,
                lr=3e-3, warmup_steps=5, max_steps=60, eval_every=30, eval_batches=2, checkpoint_every=30, log_every=10,
                device="cpu")  # exact-resume checks need CPU determinism, even on a GPU machine
    base.update(kw)
    return TrainConfig(**base)


def test_training_run_learns_and_reports(tiny_dataset, tmp_path):
    summary = train(run_config(tiny_dataset, tmp_path / "run"))
    records = [json.loads(line) for line in (tmp_path / "run" / "metrics.jsonl").read_text().splitlines()]
    evals = [r for r in records if "val_loss" in r]
    assert evals[-1]["val_loss"] < evals[0]["val_loss"] < math.log(320)
    assert summary["stop_reason"] == "finished" and summary["step"] == 60
    assert "ESTIMATE" in summary["energy_method"]  # on CPU energy is estimated, and says so
    assert (tmp_path / "run" / "model.pt").exists()

    from hfai.training.report import write_report

    report = write_report(tmp_path / "run", tiny_dataset / "tok.json", tiny_dataset, "test").read_text()
    for phrase in ("report card", "This model", "gzip", "AI-generated", "Energy"):
        assert phrase in report


def test_resume_continues_exactly(tiny_dataset, tmp_path):
    straight = tmp_path / "straight"
    train(run_config(tiny_dataset, straight, max_steps=40, checkpoint_every=20))
    split = tmp_path / "split"
    first = train(run_config(tiny_dataset, split, max_steps=40, stop_at_step=20, checkpoint_every=20))
    assert first["stop_reason"].startswith("paused at step 20")
    train(run_config(tiny_dataset, split, max_steps=40, checkpoint_every=20))
    a = load_safe(straight / "latest.pt")["model"]
    b = load_safe(split / "latest.pt")["model"]
    for key in a:
        assert torch.allclose(a[key], b[key], atol=1e-5), key


def test_time_budget_stops_cleanly(tiny_dataset, tmp_path):
    summary = train(run_config(tiny_dataset, tmp_path / "run", max_steps=100_000, max_minutes=0.02))
    assert summary["stop_reason"].startswith("time budget")
    assert load_safe(tmp_path / "run" / "latest.pt")["step"] == summary["step"]


@pytest.mark.skipif(sys.platform == "win32", reason="torchrun test uses POSIX paths")
def test_two_process_training_keeps_weights_in_sync(tiny_dataset, tmp_path):
    """Kaggle trains on two GPUs; here two CPU processes use the same code path."""
    src = str(Path(__file__).resolve().parents[1] / "src")
    overrides = json.dumps(dict(d_model=32, n_layers=2, n_heads=2, max_seq_len=32))
    command = [sys.executable, "-m", "torch.distributed.run", "--nproc_per_node=2", "--master_port=29517",
               "-m", "hfai.training", "train", "--data", str(tiny_dataset), "--tokenizer", str(tiny_dataset / "tok.json"),
               "--out", str(tmp_path / "ddp"), "--model", overrides, "--max-steps", "20", "--eval-every", "10",
               "--eval-batches", "2", "--checkpoint-every", "10", "--batch-size", "4", "--warmup-steps", "2",
               "--device", "cpu"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300,
                            env={**os.environ, "PYTHONPATH": src, "OMP_NUM_THREADS": "1"})
    assert result.returncode == 0, result.stderr[-2000:]
    summary = json.loads((tmp_path / "ddp" / "summary.json").read_text())
    assert summary["world_size"] == 2 and summary["step"] == 20
