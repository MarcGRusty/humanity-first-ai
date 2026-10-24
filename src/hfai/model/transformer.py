"""Our language model: a decoder-only Transformer, written from scratch.

In plain language: the model reads a sequence of tokens and, at every
position, predicts which token comes next. Training nudges its weights so
those predictions get better (see docs/GLOSSARY.md).

Design: a standard modern recipe, implemented here in our own code.

* token embeddings, shared with the output layer ("tied") to save parameters;
* rotary position embeddings (RoPE), which tell attention how far apart tokens are;
* pre-normalisation with RMSNorm;
* causal self-attention: each token looks only at earlier tokens;
* SwiGLU feed-forward layers;
* no bias terms.

Nothing here is loaded from an existing model: weights start random and are
learned only from our documented, openly licensed data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int
    d_model: int = 256
    n_layers: int = 6
    n_heads: int = 4
    max_seq_len: int = 512
    ffn_multiple: int = 64  # feed-forward width is rounded up to a multiple of this
    dropout: float = 0.0
    rope_base: float = 10_000.0

    @property
    def ffn_hidden(self) -> int:
        hidden = int(2 * 4 * self.d_model / 3)  # SwiGLU: keeps parameters close to a 4x MLP
        return self.ffn_multiple * math.ceil(hidden / self.ffn_multiple)

    def to_dict(self) -> dict:
        return asdict(self)


# Named sizes. Option C in docs/MODEL_OPTIONS.md is "small".
PRESETS = {
    "tiny": dict(d_model=192, n_layers=4, n_heads=3, max_seq_len=256),  # CPU proof run
    "small": dict(d_model=384, n_layers=8, n_heads=6, max_seq_len=512),  # about 25M with a 32k vocabulary
    "medium": dict(d_model=768, n_layers=12, n_heads=12, max_seq_len=1024),  # about 110M with a 32k vocabulary
}


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        normed = x.float() * torch.rsqrt(x.float().pow(2).mean(-1, keepdim=True) + self.eps)
        return normed.type_as(x) * self.weight


def rope_tables(head_dim: int, max_len: int, base: float) -> tuple[torch.Tensor, torch.Tensor]:
    inv_freq = 1.0 / (base ** (torch.arange(0, head_dim, 2).float() / head_dim))
    angles = torch.outer(torch.arange(max_len).float(), inv_freq)  # (max_len, head_dim/2)
    return angles.cos(), angles.sin()


def apply_rope(x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
    # x: (batch, heads, seq, head_dim); rotate pairs of dimensions by position-dependent angles.
    x1, x2 = x[..., 0::2], x[..., 1::2]
    cos, sin = cos[None, None], sin[None, None]
    rotated = torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
    return rotated.flatten(-2).type_as(x)


class Attention(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        if config.d_model % config.n_heads:
            raise ValueError("d_model must be divisible by n_heads")
        self.n_heads = config.n_heads
        self.head_dim = config.d_model // config.n_heads
        self.qkv = nn.Linear(config.d_model, 3 * config.d_model, bias=False)
        self.out = nn.Linear(config.d_model, config.d_model, bias=False)
        self.dropout = config.dropout

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        batch, seq, dim = x.shape
        q, k, v = self.qkv(x).split(dim, dim=-1)
        q, k, v = (t.view(batch, seq, self.n_heads, self.head_dim).transpose(1, 2) for t in (q, k, v))
        q, k = apply_rope(q, cos, sin), apply_rope(k, cos, sin)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=self.dropout if self.training else 0.0)
        return self.out(y.transpose(1, 2).reshape(batch, seq, dim))


class FeedForward(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.gate = nn.Linear(config.d_model, config.ffn_hidden, bias=False)
        self.up = nn.Linear(config.d_model, config.ffn_hidden, bias=False)
        self.down = nn.Linear(config.ffn_hidden, config.d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down(F.silu(self.gate(x)) * self.up(x))


class Block(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.norm1 = RMSNorm(config.d_model)
        self.attn = Attention(config)
        self.norm2 = RMSNorm(config.d_model)
        self.ffn = FeedForward(config)
        self.drop = nn.Dropout(config.dropout)

    def forward(self, x, cos, sin):
        x = x + self.drop(self.attn(self.norm1(x), cos, sin))
        return x + self.drop(self.ffn(self.norm2(x)))


class Transformer(nn.Module):
    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        self.embed = nn.Embedding(config.vocab_size, config.d_model)
        self.blocks = nn.ModuleList(Block(config) for _ in range(config.n_layers))
        self.norm = RMSNorm(config.d_model)
        self.head = nn.Linear(config.d_model, config.vocab_size, bias=False)
        self.head.weight = self.embed.weight  # tied: the same table reads and writes tokens
        cos, sin = rope_tables(config.d_model // config.n_heads, config.max_seq_len, config.rope_base)
        self.register_buffer("rope_cos", cos, persistent=False)
        self.register_buffer("rope_sin", sin, persistent=False)
        self.apply(self._init)
        for name, param in self.named_parameters():
            if name.endswith(("attn.out.weight", "ffn.down.weight")):
                # Smaller start for layers that add into the residual stream keeps deep stacks stable.
                nn.init.normal_(param, mean=0.0, std=0.02 / math.sqrt(2 * config.n_layers))

    @staticmethod
    def _init(module: nn.Module) -> None:
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def forward(self, idx: torch.Tensor, targets: torch.Tensor | None = None):
        seq = idx.shape[1]
        if seq > self.config.max_seq_len:
            raise ValueError(f"sequence of {seq} tokens is longer than the model's {self.config.max_seq_len}")
        x = self.embed(idx)
        cos, sin = self.rope_cos[:seq], self.rope_sin[:seq]
        for block in self.blocks:
            x = block(x, cos, sin)
        logits = self.head(self.norm(x))
        if targets is None:
            return logits, None
        loss = F.cross_entropy(logits.float().view(-1, logits.size(-1)), targets.view(-1))
        return logits, loss

    @torch.no_grad()
    def generate(
        self,
        idx: torch.Tensor,
        max_new_tokens: int,
        *,
        temperature: float = 0.8,
        top_k: int | None = 50,
        stop_token: int | None = None,
        generator: torch.Generator | None = None,
    ) -> torch.Tensor:
        """Continue a sequence one token at a time (sampling)."""
        for _ in range(max_new_tokens):
            context = idx[:, -self.config.max_seq_len:]
            logits, _ = self(context)
            logits = logits[:, -1, :].float()
            if temperature <= 0:
                next_token = logits.argmax(dim=-1, keepdim=True)
            else:
                logits = logits / temperature
                if top_k is not None:
                    kth = torch.topk(logits, min(top_k, logits.size(-1))).values[:, -1, None]
                    logits = logits.masked_fill(logits < kth, float("-inf"))
                probs = F.softmax(logits, dim=-1)
                next_token = torch.multinomial(probs, 1, generator=generator)
            idx = torch.cat((idx, next_token), dim=1)
            if stop_token is not None and bool((next_token == stop_token).all()):
                break
        return idx


def build_model(vocab_size: int, preset: str = "small", **overrides) -> Transformer:
    settings = {**PRESETS[preset], **overrides}
    return Transformer(ModelConfig(vocab_size=vocab_size, **settings))
