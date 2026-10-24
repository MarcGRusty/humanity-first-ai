"""Cleaning rules applied to every document before it can become training data.

Each rule either cleans a document or drops it with a reason, and every drop
is counted in the build report, so nothing disappears silently.

* **Licence**: the document's own licence must be on the allowed list.
* **AI-written text**: documents containing tell-tale chatbot phrases are
  dropped (charter promise P3). This is a heuristic: it catches obvious cases,
  not all AI-written text, and the remaining risk is recorded in DATA.md.
* **Personal information**: email addresses and phone-number-like strings are
  replaced with a placeholder. Heuristic: it will miss some and occasionally
  catch long numbers that are not phone numbers.
* **Too short** documents are dropped; exact duplicates are dropped.
* Text is normalised to Unicode NFC and Unix line endings, so the same words
  always become the same tokens.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
import unicodedata
from dataclasses import replace

from hfai.charter import REPO_ROOT
from hfai.data.sources import Document

MIN_CHARS = 20

AI_TEXT_MARKERS = (
    "as an ai language model",
    "as a large language model",
    "i am an ai language model",
    "i'm an ai language model",
    "as an ai developed by",
    "as an ai assistant, i",
    "regenerate response",
    "as of my last knowledge update",
    "as of my knowledge cutoff",
    "i don't have personal opinions or",
)

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{2,4}[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\w)")


def allowed_licences() -> set[str]:
    data = tomllib.loads((REPO_ROOT / "data" / "sources.toml").read_text(encoding="utf-8"))
    return set(data["policy"]["allowed_licences"])


def normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def scrub_personal_info(text: str) -> tuple[str, int]:
    text, emails = _EMAIL.subn("[email removed]", text)
    text, phones = _PHONE.subn("[phone removed]", text)
    return text, emails + phones


def looks_ai_written(text: str) -> str | None:
    lowered = text.lower()
    for marker in AI_TEXT_MARKERS:
        if marker in lowered:
            return marker
    return None


class Cleaner:
    """Stateful because it remembers what it has seen, to drop exact duplicates."""

    def __init__(self, allowed: set[str] | None = None):
        self.allowed = allowed if allowed is not None else allowed_licences()
        self.seen: set[str] = set()

    def clean(self, doc: Document) -> tuple[Document | None, str]:
        """Return (cleaned document, "kept") or (None, reason it was dropped)."""
        if doc.licence not in self.allowed:
            return None, f"licence not allowed: {doc.licence}"
        text = normalise(doc.text).strip()
        if len(text) < MIN_CHARS:
            return None, "too short"
        marker = looks_ai_written(text)
        if marker:
            return None, f"looks AI-written ({marker!r})"
        text, _ = scrub_personal_info(text)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if digest in self.seen:
            return None, "exact duplicate"
        self.seen.add(digest)
        return replace(doc, text=text), "kept"
