"""Saving and resuming training safely.

* Writes go to a temporary file first and are then renamed, so a session that
  ends mid-save (common on Kaggle) never leaves a broken checkpoint.
* Loading uses ``weights_only=True``: PyTorch then refuses to run any code
  hidden in a file. This matters once weights are shared between peers
  (milestone M6), since a malicious checkpoint could otherwise run code.
"""

from __future__ import annotations

import os
from pathlib import Path

import torch


def save_atomic(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def load_safe(path: Path, device: torch.device | str = "cpu") -> dict:
    return torch.load(path, map_location=device, weights_only=True)


def save_weights(model, config: dict, tokenizer_fingerprint: str, path: Path, extra: dict | None = None) -> None:
    """Just what is needed to use the model: weights, shape and the tokenizer it expects."""
    state = {k: v.detach().cpu() for k, v in model.state_dict().items()}
    save_atomic({"format": "hfai-weights", "version": 1, "model_config": config,
                 "tokenizer_fingerprint": tokenizer_fingerprint, "state_dict": state, **(extra or {})}, path)


def load_model(path: Path, device: torch.device | str = "cpu"):
    from hfai.model import ModelConfig, Transformer

    data = load_safe(path, device)
    if data.get("format") != "hfai-weights":
        raise ValueError(f"{path} is not an hfai weights file")
    model = Transformer(ModelConfig(**data["model_config"]))
    model.load_state_dict(data["state_dict"])
    return model, data
