"""Turn documents into training shards, with a full report of what went in.

Output folder:

* ``train.bin`` and ``val.bin``: token IDs as 16-bit little-endian numbers,
  documents separated by the ``<|endoftext|>`` token. The validation split
  (text the model never trains on, used to measure learning honestly) is
  chosen by a fingerprint of each document's ID, so it is the same every time.
* ``report.json``: for every source, how many documents were kept or dropped
  and why, bytes, tokens and licences, plus the tokenizer's fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import sys
from array import array
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from hfai.data.filters import Cleaner
from hfai.data.sources import Document
from hfai.tokenizer import Tokenizer


def is_validation(doc: Document, val_fraction: float) -> bool:
    digest = hashlib.sha256(f"{doc.source}/{doc.doc_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < val_fraction


def _write(path: Path, ids: array) -> None:
    if sys.byteorder != "little":
        ids = array("H", ids)
        ids.byteswap()
    with path.open("ab") as handle:
        ids.tofile(handle)


def build(
    documents: Iterable[Document],
    tokenizer: Tokenizer,
    out_dir: Path,
    *,
    val_fraction: float = 0.02,
    cleaner: Cleaner | None = None,
) -> dict:
    if tokenizer.vocab_size > 65_536:
        raise ValueError("token IDs must fit in 16 bits")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("train.bin", "val.bin"):
        (out_dir / name).unlink(missing_ok=True)
    cleaner = cleaner or Cleaner()
    eot = tokenizer.token_id("<|endoftext|>")

    reasons: dict[str, Counter] = defaultdict(Counter)
    stats: dict[str, Counter] = defaultdict(Counter)
    licences: dict[str, Counter] = defaultdict(Counter)
    languages: dict[str, Counter] = defaultdict(Counter)

    for doc in documents:
        cleaned, reason = cleaner.clean(doc)
        reasons[doc.source][reason] += 1
        if cleaned is None:
            continue
        ids = array("H", tokenizer.encode(cleaned.text))
        ids.append(eot)
        split = "val" if is_validation(cleaned, val_fraction) else "train"
        _write(out_dir / f"{split}.bin", ids)
        stats[doc.source][f"{split}_tokens"] += len(ids)
        stats[doc.source][f"{split}_documents"] += 1
        stats[doc.source]["bytes"] += len(cleaned.text.encode("utf-8"))
        licences[doc.source][cleaned.licence] += 1
        languages[doc.source][cleaned.language] += 1

    report = {
        "tokenizer_fingerprint": tokenizer.fingerprint,
        "vocab_size": tokenizer.vocab_size,
        "val_fraction": val_fraction,
        "sources": {
            source: {
                "kept_and_dropped": dict(reasons[source]),
                **dict(stats[source]),
                "licences": dict(licences[source]),
                "languages": len(languages[source]),
            }
            for source in reasons
        },
        "totals": {
            "train_tokens": sum(s["train_tokens"] for s in stats.values()),
            "val_tokens": sum(s["val_tokens"] for s in stats.values()),
            "bytes": sum(s["bytes"] for s in stats.values()),
        },
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report
