"""Where training text comes from: one adapter per source in data/sources.toml.

Every document carries its source ID and licence from the moment it is read,
so the final report can say exactly what the model learned from.

Adapters:

* ``nltk-gutenberg``: public-domain books from NLTK's Project Gutenberg
  selection, downloaded from GitHub and checked against a pinned fingerprint.
  Small (about 9 MB, English only): used for the CPU proof run in M3.
* ``unicode-cldr``: everyday words (names of languages, countries, months,
  days, ...) in hundreds of languages, from the Unicode CLDR data shipped in
  the Babel package. Used to train and measure the tokenizer's coverage of
  writing systems; it is word lists, not running text.
* Hugging Face sources (``common-pile``, ``common-corpus``, ``wikipedia``):
  streamed with the ``datasets`` library on Kaggle. **UNVERIFIED**: their
  field names and licence labels have not yet been checked against the live
  data (the development container cannot reach Hugging Face). They fail
  closed: unexpected fields stop the run, and documents with unrecognised
  licence labels are dropped and counted for human review.
"""

from __future__ import annotations

import hashlib
import tomllib
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from hfai.charter import REPO_ROOT


@dataclass(frozen=True)
class Document:
    source: str
    doc_id: str
    text: str
    licence: str
    language: str


def load_sources() -> dict[str, dict]:
    data = tomllib.loads((REPO_ROOT / "data" / "sources.toml").read_text(encoding="utf-8"))
    return {source["id"]: source for source in data["sources"]}


def check_allowed(source_id: str) -> dict:
    """Refuse any source that the data policy does not allow."""
    sources = load_sources()
    if source_id not in sources:
        raise ValueError(f"'{source_id}' is not listed in data/sources.toml")
    source = sources[source_id]
    if source["status"] == "excluded":
        raise ValueError(f"'{source_id}' is excluded: {source.get('reason', '')}")
    if not source["human_written"]:
        raise ValueError(f"'{source_id}' is not human-written")
    return source


# --- NLTK Project Gutenberg selection --------------------------------------------

GUTENBERG_URL = "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/packages/corpora/gutenberg.zip"
GUTENBERG_SHA256 = "2d3c3ab548c653944310f37f536443ec85d0a0ad855fcae217a0c9efdce2d611"
# Public domain in the US and in countries with copyright of life + 70 years or less.
# Left out: burgess-busterbrown and bryant-stories (authors died 1965 and 1967, still in
# copyright in some countries) and bible-kjv (Crown rights in the UK; a single religion's
# scripture on its own would also skew the data).
GUTENBERG_FILES = (
    "austen-emma.txt", "austen-persuasion.txt", "austen-sense.txt", "blake-poems.txt",
    "carroll-alice.txt", "chesterton-ball.txt", "chesterton-brown.txt", "chesterton-thursday.txt",
    "edgeworth-parents.txt", "melville-moby_dick.txt", "milton-paradise.txt",
    "shakespeare-caesar.txt", "shakespeare-hamlet.txt", "shakespeare-macbeth.txt", "whitman-leaves.txt",
)


def fetch_gutenberg(cache_dir: Path, expected_sha256: str | None = None) -> Path:
    """Download the zip once into its own folder and verify its fingerprint."""
    folder = cache_dir / "nltk-gutenberg"
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / "gutenberg.zip"
    if not archive.exists():
        with urllib.request.urlopen(GUTENBERG_URL, timeout=60) as response:  # noqa: S310 (fixed https URL)
            archive.write_bytes(response.read())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected = expected_sha256 or GUTENBERG_SHA256
    if digest != expected:
        raise ValueError(f"gutenberg.zip fingerprint {digest} does not match the pinned {expected}")
    return archive


def iter_gutenberg(cache_dir: Path) -> Iterator[Document]:
    archive = fetch_gutenberg(cache_dir)
    with zipfile.ZipFile(archive) as zf:
        names = {Path(name).name: name for name in zf.namelist()}
        for filename in GUTENBERG_FILES:
            if filename not in names:
                raise ValueError(f"{filename} missing from gutenberg.zip")
            raw = zf.read(names[filename])  # read into memory; nothing is extracted to disk
            text = raw.decode("latin-1") if b"\x00" in raw else raw.decode("utf-8", errors="replace")
            # Split each book into sections, so the validation split samples passages
            # from many books rather than holding out one whole book.
            for number, section in enumerate(split_sections(text)):
                yield Document("nltk-gutenberg", f"{filename}#{number}", section, "public-domain", "en")


def split_sections(text: str, target_chars: int = 20_000) -> list[str]:
    """Cut text into pieces of about target_chars, at paragraph boundaries."""
    sections, current, size = [], [], 0
    for paragraph in text.split("\n\n"):
        current.append(paragraph)
        size += len(paragraph) + 2
        if size >= target_chars:
            sections.append("\n\n".join(current))
            current, size = [], 0
    if current:
        sections.append("\n\n".join(current))
    return sections


# --- Unicode CLDR (via Babel) ----------------------------------------------------------


def _cldr_text(locale, part: str = "all") -> str:
    """Everyday words in this locale's own language.

    part="train": names of languages and territories (used to train tokenizers).
    part="eval":  names of scripts, months and days, held out to measure them.
    """
    train_parts = [*locale.languages.values(), *locale.territories.values()]
    eval_parts = [locale.display_name, *locale.scripts.values(),
                  *locale.months["format"]["wide"].values(), *locale.days["format"]["wide"].values()]
    if part == "train":
        parts = train_parts
    elif part == "eval":
        seen = set(train_parts)
        parts = [p for p in eval_parts if p not in seen]  # truly held out: never in the training part
    else:
        parts = train_parts + eval_parts
    return "\n".join(dict.fromkeys(p for p in parts if p))


def cldr_locales() -> list[str]:
    from babel import localedata

    return sorted(l for l in localedata.locale_identifiers() if "_" not in l and l != "root")


def iter_cldr(cache_dir: Path | None = None, part: str = "train") -> Iterator[Document]:
    from babel import Locale

    for identifier in cldr_locales():
        locale = Locale.parse(identifier)
        text = _cldr_text(locale, part)
        if text:
            yield Document("unicode-cldr", identifier, text, "Unicode-3.0", identifier)


# --- Hugging Face (Kaggle) ---------------------------------------------------------------

# UNVERIFIED field names and licence labels: see the module docstring.
HF_SOURCES = {
    "common-pile": {"dataset": "common-pile/comma_v0.1_training_dataset", "config": None,
                    "text": "text", "licence_field": None, "licence": "per-document-open", "language": "en"},
    "common-corpus": {"dataset": "PleIAs/common_corpus", "config": None,
                      "text": "text", "licence_field": "license", "licence": None, "language_field": "language"},
    "wikipedia": {"dataset": "wikimedia/wikipedia", "config": "20231101.{lang}",
                  "text": "text", "licence_field": None, "licence": "CC-BY-SA-4.0"},
}
# Licence labels accepted from per-document metadata (lower-cased). Anything else is dropped.
OPEN_LICENCE_LABELS = {
    "public domain": "public-domain", "public-domain": "public-domain", "cc0": "CC0-1.0", "cc0-1.0": "CC0-1.0",
    "cc-by": "CC-BY-4.0", "cc-by-4.0": "CC-BY-4.0", "cc by 4.0": "CC-BY-4.0",
    "cc-by-sa": "CC-BY-SA-4.0", "cc-by-sa-4.0": "CC-BY-SA-4.0", "cc by-sa 4.0": "CC-BY-SA-4.0",
    "cc-by-sa-3.0": "CC-BY-SA-3.0", "mit": "MIT", "apache-2.0": "Apache-2.0", "bsd-3-clause": "BSD-3-Clause",
}


def normalise_licence(label: str | None) -> str | None:
    if label is None:
        return None
    return OPEN_LICENCE_LABELS.get(str(label).strip().lower())


def iter_huggingface(source_id: str, language: str = "en", limit: int | None = None,
                     shuffle: bool = False) -> Iterator[Document]:
    from datasets import load_dataset  # only available where Hugging Face is reachable (Kaggle)

    spec = HF_SOURCES[source_id]
    config = spec["config"].format(lang=language) if spec["config"] else None
    stream = load_dataset(spec["dataset"], config, split="train", streaming=True)
    if shuffle:
        # Shuffles the order of the dataset's files and mixes rows within a buffer,
        # so a partial download is not dominated by whichever part comes first.
        stream = stream.shuffle(seed=0, buffer_size=10_000)
    for index, row in enumerate(stream):
        if limit is not None and index >= limit:
            return
        if spec["text"] not in row:
            raise ValueError(f"{source_id}: expected a '{spec['text']}' field, found {sorted(row)}")
        if spec["licence_field"]:
            if spec["licence_field"] not in row:
                raise ValueError(f"{source_id}: expected a '{spec['licence_field']}' field, found {sorted(row)}")
            licence = normalise_licence(row[spec["licence_field"]]) or f"UNRECOGNISED:{row[spec['licence_field']]}"
        else:
            licence = spec["licence"]
        lang = row.get(spec.get("language_field", ""), language) if spec.get("language_field") else language
        yield Document(source_id, str(row.get("id", index)), row[spec["text"]], licence, str(lang))


def iter_source(source_id: str, cache_dir: Path, **kwargs) -> Iterator[Document]:
    check_allowed(source_id)
    if source_id == "nltk-gutenberg":
        return iter_gutenberg(cache_dir)
    if source_id == "unicode-cldr":
        return iter_cldr(cache_dir)
    if source_id in HF_SOURCES:
        return iter_huggingface(source_id, **kwargs)
    raise ValueError(f"no adapter for '{source_id}' yet")

