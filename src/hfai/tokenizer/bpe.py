"""Our own byte-level BPE tokenizer, trained from scratch.

How it works, in plain language:

* Any text, in any writing system, is stored by computers as bytes (UTF-8).
  The tokenizer starts with 256 basic tokens, one per possible byte, so it can
  represent every language from day one, with nothing "unknown".
* Training looks at a sample of text, finds the pair of neighbouring tokens
  that occurs most often, and adds a new token for that pair (a "merge").
  It repeats until the vocabulary reaches the chosen size. Common words end
  up as single tokens; rare words are spelled out in smaller pieces.
* Encoding applies the learned merges in the order they were learned.
  Decoding just joins the bytes back together.

Special tokens (such as the end-of-document marker) are never produced from
ordinary text: if a document or a person types "<|endoftext|>", it is
encoded as plain characters. This stops text from impersonating the
structure of a conversation (a defence against prompt injection).

No pretrained vocabulary is used. The trained tokenizer is saved in our own
JSON format, together with where its training text came from.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable

from hfai.tokenizer.pretokenize import pretokenize, unicode_version

FORMAT = "hfai-bpe"
FORMAT_VERSION = 1
SPECIAL_TOKENS = ("<|endoftext|>", "<|pad|>", "<|user|>", "<|ai|>", "<|source|>", "<|end_source|>")
MAX_VOCAB = 65_536  # token ids are stored as 16-bit numbers
CACHE_LIMIT = 500_000
HEAP_COMPACT_MIN = 2_000_000  # rebuild the merge queue when stale entries pile up beyond this


def _merge(ids: list[int], pair: tuple[int, int], new_id: int) -> list[int]:
    out, i, n = [], 0, len(ids)
    a, b = pair
    while i < n:
        if i < n - 1 and ids[i] == a and ids[i + 1] == b:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out


class Tokenizer:
    def __init__(self, merges: list[tuple[int, int]], special_tokens: Iterable[str] = SPECIAL_TOKENS, meta: dict | None = None):
        self.merges = [tuple(pair) for pair in merges]
        self.ranks = {pair: 256 + index for index, pair in enumerate(self.merges)}
        self.vocab: list[bytes] = [bytes([i]) for i in range(256)]
        for a, b in self.merges:
            self.vocab.append(self.vocab[a] + self.vocab[b])
        self.special = {token: len(self.vocab) + i for i, token in enumerate(special_tokens)}
        self.special_by_id = {i: token for token, i in self.special.items()}
        self.meta = meta or {}
        if self.vocab_size > MAX_VOCAB:
            raise ValueError(f"vocabulary of {self.vocab_size} is larger than {MAX_VOCAB}")
        self._cache: dict[str, tuple[int, ...]] = {}

    @property
    def vocab_size(self) -> int:
        return len(self.vocab) + len(self.special)

    def token_id(self, special: str) -> int:
        return self.special[special]

    # --- encoding -----------------------------------------------------------

    def _encode_chunk(self, chunk: str) -> tuple[int, ...]:
        cached = self._cache.get(chunk)
        if cached is not None:
            return cached
        ids = list(chunk.encode("utf-8"))
        ranks = self.ranks
        while len(ids) >= 2:
            best, best_rank = None, None
            for pair in zip(ids, ids[1:]):
                rank = ranks.get(pair)
                if rank is not None and (best_rank is None or rank < best_rank):
                    best, best_rank = pair, rank
            if best is None:
                break
            ids = _merge(ids, best, best_rank)
        result = tuple(ids)
        if len(self._cache) >= CACHE_LIMIT:
            self._cache.clear()
        self._cache[chunk] = result
        return result

    def encode(self, text: str, allowed_special: Iterable[str] = ()) -> list[int]:
        """Text to token ids. Special tokens are only recognised if explicitly allowed."""
        allowed = [s for s in allowed_special if s in self.special]
        ids: list[int] = []
        if allowed:
            pattern = "(" + "|".join(re.escape(s) for s in allowed) + ")"
            parts = re.split(pattern, text)
        else:
            parts = [text]
        for part in parts:
            if part in allowed:
                ids.append(self.special[part])
            elif part:
                for chunk in pretokenize(part):
                    ids.extend(self._encode_chunk(chunk))
        return ids

    # --- decoding -----------------------------------------------------------

    def decode_bytes(self, ids: Iterable[int]) -> bytes:
        out = []
        for i in ids:
            if i < len(self.vocab):
                out.append(self.vocab[i])
            elif i in self.special_by_id:
                out.append(self.special_by_id[i].encode("utf-8"))
            else:
                raise ValueError(f"unknown token id {i}")
        return b"".join(out)

    def decode(self, ids: Iterable[int]) -> str:
        # A sequence cut mid-character (possible while generating) shows a replacement mark.
        return self.decode_bytes(ids).decode("utf-8", errors="replace")

    # --- saving -------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "unicode_version": self.meta.get("unicode_version", unicode_version()),
            "vocab_size": self.vocab_size,
            "special_tokens": list(self.special),
            "merges": [list(pair) for pair in self.merges],
            "training": self.meta.get("training", {}),
        }

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False), encoding="utf-8")

    @property
    def fingerprint(self) -> str:
        body = json.dumps({"merges": self.merges, "special": list(self.special)}, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path | str) -> "Tokenizer":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), str(path))

    @classmethod
    def from_dict(cls, data: dict, path: str = "tokenizer data") -> "Tokenizer":
        if data.get("format") != FORMAT or data.get("version") != FORMAT_VERSION:
            raise ValueError(f"{path} is not an {FORMAT} v{FORMAT_VERSION} tokenizer file")
        merges = [tuple(pair) for pair in data["merges"]]
        for index, (a, b) in enumerate(merges):
            if not (0 <= a < 256 + index and 0 <= b < 256 + index):
                raise ValueError(f"merge {index} refers to a token that does not exist yet")
        return cls(merges, data["special_tokens"], {"unicode_version": data["unicode_version"], "training": data["training"]})


def train(
    texts: Iterable[str],
    vocab_size: int,
    *,
    special_tokens: Iterable[str] = SPECIAL_TOKENS,
    min_frequency: int = 2,
    training_info: dict | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Tokenizer:
    """Learn merges from text until the vocabulary reaches ``vocab_size``.

    Deterministic: the same texts in the same order give the same tokenizer.
    """
    special_tokens = tuple(special_tokens)
    n_merges = vocab_size - 256 - len(special_tokens)
    if n_merges < 0 or vocab_size > MAX_VOCAB:
        raise ValueError(f"vocab_size must be between {256 + len(special_tokens)} and {MAX_VOCAB}")

    chunk_counts: Counter[str] = Counter()
    total_bytes = 0
    digest = hashlib.sha256()
    for text in texts:
        chunk_counts.update(pretokenize(text))
        encoded = text.encode("utf-8")
        total_bytes += len(encoded)
        digest.update(encoded)

    words = [list(chunk.encode("utf-8")) for chunk in chunk_counts]
    freqs = list(chunk_counts.values())
    pair_counts: defaultdict[tuple[int, int], int] = defaultdict(int)
    where: defaultdict[tuple[int, int], set[int]] = defaultdict(set)
    for index, word in enumerate(words):
        for pair in zip(word, word[1:]):
            pair_counts[pair] += freqs[index]
            where[pair].add(index)
    heap = [(-count, pair) for pair, count in pair_counts.items()]
    heapq.heapify(heap)

    merges: list[tuple[int, int]] = []
    while len(merges) < n_merges and heap:
        neg_count, pair = heapq.heappop(heap)
        count = pair_counts.get(pair, 0)
        if count != -neg_count:
            continue  # stale entry; the current count was pushed when it changed
        if count < min_frequency:
            break
        new_id = 256 + len(merges)
        merges.append(pair)
        touched: set[tuple[int, int]] = set()
        for index in sorted(where[pair]):
            word, freq = words[index], freqs[index]
            old_pairs = list(zip(word, word[1:]))
            new_word = _merge(word, pair, new_id)
            new_pairs = list(zip(new_word, new_word[1:]))
            for p in old_pairs:
                pair_counts[p] -= freq
            for p in new_pairs:
                pair_counts[p] += freq
            old_set, new_set = set(old_pairs), set(new_pairs)
            for p in old_set - new_set:
                where[p].discard(index)
            for p in new_set - old_set:
                where[p].add(index)
            touched |= old_set | new_set
            words[index] = new_word
        pair_counts.pop(pair, None)
        where.pop(pair, None)
        for p in touched:
            count = pair_counts.get(p, 0)
            if count > 0:
                heapq.heappush(heap, (-count, p))
            elif p in pair_counts:
                del pair_counts[p]
        if len(heap) > HEAP_COMPACT_MIN and len(heap) > 4 * len(pair_counts):
            # Drop stale entries so memory stays bounded on large samples. Same order, same result.
            heap = [(-count, p) for p, count in pair_counts.items() if count > 0]
            heapq.heapify(heap)
        if progress is not None and len(merges) % 1000 == 0:
            progress(len(merges), n_merges)

    info = dict(training_info or {})
    info.update({"bytes": total_bytes, "sha256": digest.hexdigest(), "unique_chunks": len(words),
                 "merges_learned": len(merges), "merges_requested": n_merges})
    return Tokenizer(merges, special_tokens, {"unicode_version": unicode_version(), "training": info})
