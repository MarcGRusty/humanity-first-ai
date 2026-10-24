"""Measuring how well the language model predicts text it has never trained on.

* **Loss** (cross-entropy, in nats per token): how surprised the model is by
  the real next token, on average. Lower is better.
* **Perplexity** = e^loss: roughly "how many tokens the model is choosing
  between". A model guessing uniformly from 8,192 tokens has perplexity 8,192.
* **Bits per byte**: the same surprise measured per byte of original text. It
  does not depend on the tokenizer, so models with different tokenizers can be
  compared fairly. Plain UTF-8 text is 8 bits per byte; good modern compressors
  reach about 2 bits per byte on English text.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F

from hfai.tokenizer import Tokenizer


def token_byte_lengths(tokenizer: Tokenizer) -> torch.Tensor:
    lengths = [len(piece) for piece in tokenizer.vocab] + [0] * len(tokenizer.special)
    return torch.tensor(lengths, dtype=torch.float64)


@torch.no_grad()
def evaluate(model, batches, byte_lengths: torch.Tensor, device: torch.device, autocast=None) -> dict:
    model.eval()
    total_nats, total_tokens, total_bytes = 0.0, 0, 0.0
    lengths = byte_lengths.to(device)
    for x, y in batches:
        x, y = x.to(device), y.to(device)
        if autocast is not None:
            with autocast():
                logits, _ = model(x)
        else:
            logits, _ = model(x)
        losses = F.cross_entropy(logits.float().view(-1, logits.size(-1)), y.view(-1), reduction="none")
        total_nats += losses.double().sum().item()
        total_tokens += y.numel()
        total_bytes += lengths[y.view(-1)].sum().item()
    model.train()
    loss = total_nats / total_tokens
    return {
        "val_loss": loss,
        "val_perplexity": math.exp(min(loss, 50)),
        "val_bits_per_byte": (total_nats / math.log(2)) / total_bytes if total_bytes else float("nan"),
        "val_tokens": total_tokens,
    }
