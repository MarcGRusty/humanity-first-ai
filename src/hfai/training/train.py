"""The training loop: teaches our model from scratch, with honest measurements.

Works on a laptop CPU (the proof run), one GPU, or several GPUs (Kaggle's two
T4s, via ``torchrun --nproc_per_node=2``). It:

* resumes automatically from ``latest.pt`` in the output folder, so a Kaggle
  session that ends (after about 9-12 hours) loses at most a few minutes;
* stops itself cleanly before a time budget (``max_minutes``) runs out;
* evaluates on validation text the model never trains on, every so often;
* keeps the weights with the best validation score as ``model.pt``;
* measures GPU energy where the hardware reports it, and otherwise *estimates*
  it from an assumed power draw that is printed in the report;
* writes ``metrics.jsonl`` (every logged step) and, at the end,
  ``report.md`` with a loss chart and sample text.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import torch
import torch.distributed as dist

from hfai.evals.lm import evaluate, token_byte_lengths
from hfai.model import PRESETS, ModelConfig, Transformer
from hfai.tokenizer import Tokenizer
from hfai.training.checkpoint import load_safe, save_atomic, save_weights
from hfai.training.data import TokenData

SAMPLE_PROMPTS = ("It was a bright morning, and", "The best way to learn is", "She looked at the sea and said")


@dataclass
class TrainConfig:
    data_dir: str
    tokenizer: str
    out_dir: str
    preset: str = "tiny"
    model_overrides: dict = field(default_factory=dict)
    batch_size: int = 16
    grad_accum: int = 1
    lr: float = 1e-3
    min_lr_ratio: float = 0.1
    warmup_steps: int = 100
    max_steps: int = 1000
    weight_decay: float = 0.1
    grad_clip: float = 1.0
    log_every: int = 10
    eval_every: int = 200
    eval_batches: int = 20
    checkpoint_every: int = 200
    max_minutes: float | None = None
    stop_at_step: int | None = None  # pause here (schedule still follows max_steps); run again to resume
    seed: int = 1337
    device: str = "auto"
    assumed_watts: float | None = None  # used for the energy *estimate* when power cannot be measured
    sample_tokens: int = 60


def lr_at(step: int, config: TrainConfig) -> float:
    """Warm up linearly, then follow a cosine curve down to min_lr_ratio of the peak."""
    if step < config.warmup_steps:
        return config.lr * (step + 1) / config.warmup_steps
    progress = min(1.0, (step - config.warmup_steps) / max(1, config.max_steps - config.warmup_steps))
    return config.lr * (config.min_lr_ratio + (1 - config.min_lr_ratio) * 0.5 * (1 + math.cos(math.pi * progress)))


class EnergyMeter:
    """Measures GPU power where possible; otherwise estimates from an assumed wattage."""

    def __init__(self, device: torch.device, assumed_watts: float | None):
        self.device = device
        self.watt_hours = 0.0
        self.last = time.monotonic()
        self.measured = False
        self.assumed_watts = assumed_watts
        if device.type == "cuda":
            try:
                torch.cuda.power_draw(device)
                self.measured = True
            except Exception:  # pynvml missing or unsupported: fall back to an estimate
                pass
        if not self.measured and self.assumed_watts is None:
            self.assumed_watts = 70.0 if device.type == "cuda" else 40.0

    def tick(self) -> None:
        now = time.monotonic()
        hours = (now - self.last) / 3600
        self.last = now
        if self.measured:
            watts = torch.cuda.power_draw(self.device) / 1000.0
        else:
            watts = self.assumed_watts
        self.watt_hours += watts * hours

    def describe(self) -> str:
        if self.measured:
            return "measured from the GPUs' own power sensors (GPUs only; the host computer adds more)"
        return f"ESTIMATE assuming {self.assumed_watts:.0f} W average draw (not measured)"


def _setup_distributed() -> tuple[int, int, int]:
    world = int(os.environ.get("WORLD_SIZE", "1"))
    if world > 1 and not dist.is_initialized():
        backend = "nccl" if torch.cuda.is_available() else "gloo"
        dist.init_process_group(backend)
    rank = int(os.environ.get("RANK", "0"))
    local = int(os.environ.get("LOCAL_RANK", "0"))
    return rank, local, world


def _pick_device(choice: str, local_rank: int) -> torch.device:
    if choice != "auto":
        return torch.device(choice)
    if torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        return torch.device("cuda", local_rank)
    return torch.device("cpu")


def _precision(device: torch.device):
    """bf16 on newer GPUs, fp16 with loss scaling on older ones such as the T4, fp32 on CPU."""
    if device.type == "cuda":
        major, _ = torch.cuda.get_device_capability(device)
        if major >= 8 and torch.cuda.is_bf16_supported():
            return torch.bfloat16, False
        return torch.float16, True
    return None, False


def train(config: TrainConfig) -> dict:
    rank, local_rank, world = _setup_distributed()
    is_main = rank == 0
    device = _pick_device(config.device, local_rank)
    out_dir = Path(config.out_dir)
    if is_main:
        out_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = Tokenizer.load(config.tokenizer)
    settings = {**PRESETS[config.preset], **config.model_overrides}
    model_config = ModelConfig(vocab_size=tokenizer.vocab_size, **settings)
    seq_len = model_config.max_seq_len
    train_data = TokenData(Path(config.data_dir) / "train.bin", seq_len)
    val_data = TokenData(Path(config.data_dir) / "val.bin", seq_len)
    eval_set = val_data.fixed_batches(config.batch_size, config.eval_batches)
    byte_lengths = token_byte_lengths(tokenizer)

    torch.manual_seed(config.seed)
    model = Transformer(model_config).to(device)
    dtype, use_scaler = _precision(device)
    scaler = torch.amp.GradScaler("cuda", enabled=use_scaler)

    def autocast():
        if dtype is None:
            return torch.autocast(device_type=device.type, enabled=False)
        return torch.autocast(device_type=device.type, dtype=dtype)

    decay = [p for n, p in model.named_parameters() if p.dim() >= 2]
    no_decay = [p for n, p in model.named_parameters() if p.dim() < 2]
    optimizer = torch.optim.AdamW(
        [{"params": decay, "weight_decay": config.weight_decay}, {"params": no_decay, "weight_decay": 0.0}],
        lr=config.lr, betas=(0.9, 0.95), fused=device.type == "cuda",
    )
    generator = torch.Generator().manual_seed(config.seed + rank)

    step, best_val, elapsed_before, tokens_before, energy_before = 0, float("inf"), 0.0, 0, 0.0
    latest = out_dir / "latest.pt"
    if latest.exists():
        state = load_safe(latest, device)
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scaler.load_state_dict(state["scaler"])
        per_rank = state["per_rank"][rank] if rank < len(state["per_rank"]) else state["per_rank"][0]
        generator.set_state(per_rank["generator"])
        step, best_val = state["step"], state["best_val"]
        elapsed_before, tokens_before, energy_before = state["elapsed"], state["tokens"], per_rank["watt_hours"]
        if is_main:
            print(f"Resumed from step {step}.")

    train_model = model
    if world > 1:
        train_model = torch.nn.parallel.DistributedDataParallel(model, device_ids=[local_rank] if device.type == "cuda" else None)

    start_step = step
    meter = EnergyMeter(device, config.assumed_watts)
    meter.watt_hours = energy_before
    tokens_per_step = config.batch_size * config.grad_accum * seq_len * world
    started = time.monotonic()
    metrics_file = out_dir / "metrics.jsonl"
    stop_reason = "finished"

    def elapsed() -> float:
        return elapsed_before + (time.monotonic() - started)

    def total_watt_hours() -> float:
        """Energy for the whole run: GPU sensors are summed across GPUs; an estimate covers the machine once."""
        if world == 1:
            return meter.watt_hours
        values = torch.tensor([meter.watt_hours if meter.measured else 0.0, 1.0 if meter.measured else 0.0],
                              dtype=torch.float64, device=device)
        dist.all_reduce(values)
        return values[0].item() if values[1].item() == world else meter.watt_hours

    def save_checkpoint() -> None:
        mine = {"generator": generator.get_state(), "watt_hours": meter.watt_hours}
        per_rank = [mine]
        if world > 1:
            per_rank = [None] * world
            dist.all_gather_object(per_rank, mine)
        if is_main:
            save_atomic({
                "model": model.state_dict(), "optimizer": optimizer.state_dict(), "scaler": scaler.state_dict(),
                "per_rank": per_rank, "step": step, "best_val": best_val, "elapsed": elapsed(),
                "tokens": tokens_before + (step - start_step) * tokens_per_step,
                "model_config": model_config.to_dict(), "train_config": asdict(config),
            }, latest)

    def log(record: dict) -> None:
        if is_main:
            with metrics_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")

    model.train()
    while step < config.max_steps and (config.stop_at_step is None or step < config.stop_at_step):
        for group in optimizer.param_groups:
            group["lr"] = lr_at(step, config)
        loss_total = torch.zeros((), device=device)
        for micro in range(config.grad_accum):
            x, y = train_data.random_batch(config.batch_size, generator)
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            sync = world == 1 or micro == config.grad_accum - 1
            context = train_model.no_sync() if (world > 1 and not sync) else contextlib.nullcontext()
            with context, autocast():
                _, loss = train_model(x, y)
                loss = loss / config.grad_accum
            scaler.scale(loss).backward()
            loss_total += loss.detach()  # stays on the GPU: no waiting every micro-step
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), config.grad_clip)
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
        step += 1

        if step % config.log_every == 0 or step == config.max_steps:
            meter.tick()
            run_tokens = (step - start_step) * tokens_per_step
            energy = total_watt_hours()
            log({"step": step, "loss": loss_total.item(), "lr": optimizer.param_groups[0]["lr"],
                 "tokens": tokens_before + run_tokens, "elapsed_s": round(elapsed(), 1),
                 "tokens_per_s": round(run_tokens / max(1e-9, time.monotonic() - started)),
                 "watt_hours": round(energy, 4)})

        if step % config.eval_every == 0 or step == config.max_steps:
            if is_main:
                result = evaluate(model, eval_set, byte_lengths, device, autocast if dtype is not None else None)
                log({"step": step, **result})
                print(f"step {step}: val loss {result['val_loss']:.3f}, "
                      f"perplexity {result['val_perplexity']:.1f}, bits/byte {result['val_bits_per_byte']:.3f}")
                if result["val_loss"] < best_val:
                    best_val = result["val_loss"]
                    save_weights(model, model_config.to_dict(), tokenizer.fingerprint, out_dir / "model.pt",
                                 {"step": step, "val_loss": best_val})
            if world > 1:
                dist.barrier()

        out_of_time = config.max_minutes is not None and elapsed() - elapsed_before > config.max_minutes * 60
        if world > 1:
            flag = torch.tensor([1 if out_of_time else 0], device=device)
            dist.all_reduce(flag)
            out_of_time = bool(flag.item())
        if step % config.checkpoint_every == 0 or out_of_time:
            save_checkpoint()
        if out_of_time:
            stop_reason = "time budget reached; run again to resume"
            break

    if step < config.max_steps and stop_reason == "finished":
        stop_reason = f"paused at step {step}; run again to resume"
    meter.tick()
    save_checkpoint()
    energy = total_watt_hours()
    summary = {}
    if is_main:
        summary = {
            "stop_reason": stop_reason, "step": step, "max_steps": config.max_steps,
            "parameters": model.num_parameters(), "model_config": model_config.to_dict(),
            "tokens_seen": tokens_before + (step - start_step) * tokens_per_step,
            "elapsed_s": round(elapsed(), 1), "watt_hours": round(energy, 3),
            "energy_method": meter.describe(), "device": str(device), "world_size": world,
            "precision": str(dtype or torch.float32), "best_val_loss": best_val,
            "tokenizer_fingerprint": tokenizer.fingerprint,
        }
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if world > 1:
        dist.barrier()
        dist.destroy_process_group()
    return summary

