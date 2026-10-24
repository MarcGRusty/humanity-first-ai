"""Reading tokenized shards (from hfai.data.pipeline) as training batches."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch


class TokenData:
    """A file of 16-bit token IDs, read without loading it all into memory."""

    def __init__(self, path: Path | str, seq_len: int):
        self.path = Path(path)
        self.tokens = np.memmap(self.path, dtype="<u2", mode="r")
        self.seq_len = seq_len
        if len(self.tokens) <= seq_len + 1:
            raise ValueError(f"{self.path} has only {len(self.tokens)} tokens; need more than {seq_len + 1}")

    def __len__(self) -> int:
        return len(self.tokens)

    def _window(self, start: int) -> tuple[torch.Tensor, torch.Tensor]:
        chunk = torch.from_numpy(self.tokens[start:start + self.seq_len + 1].astype(np.int64))
        return chunk[:-1], chunk[1:]

    def random_batch(self, batch_size: int, generator: torch.Generator) -> tuple[torch.Tensor, torch.Tensor]:
        """Random windows: the model sees text in a different order every time."""
        high = len(self.tokens) - self.seq_len - 1
        starts = torch.randint(0, high, (batch_size,), generator=generator).tolist()
        xs, ys = zip(*(self._window(s) for s in starts))
        return torch.stack(xs), torch.stack(ys)

    def fixed_batches(self, batch_size: int, n_batches: int) -> list[tuple[torch.Tensor, torch.Tensor]]:
        """The same evenly spaced windows every time, so evaluations are comparable."""
        high = len(self.tokens) - self.seq_len - 1
        total = batch_size * n_batches
        starts = np.linspace(0, high, num=total, dtype=np.int64).tolist()
        batches = []
        for b in range(n_batches):
            xs, ys = zip(*(self._window(s) for s in starts[b * batch_size:(b + 1) * batch_size]))
            batches.append((torch.stack(xs), torch.stack(ys)))
        return batches
