"""Measure how well a tokenizer covers the world's languages and writing systems.

For each language in Unicode CLDR, using held-out everyday words (names of
scripts, months and days, which tokenizer training does not use), it checks:

* **Round trip**: text goes in and comes back identical. This is coverage
  level L0 in docs/LANGUAGES.md.
* **Characters per token**: higher means the language is encoded more
  efficiently. A language at about 1 character per token or less is
  being spelled out byte by byte: the tokenizer has learned little about it,
  so the model will find it harder and slower.

Honest caveat: these are word lists, not running text. They show coverage of
writing systems, not how well the model will understand a language.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass

from hfai.tokenizer.bpe import Tokenizer


@dataclass(frozen=True)
class LanguageResult:
    code: str
    name: str
    script: str
    chars: int
    tokens: int
    round_trip: bool

    @property
    def chars_per_token(self) -> float:
        return self.chars / self.tokens if self.tokens else 0.0


def dominant_script(text: str) -> str:
    counts = Counter()
    for ch in text:
        if unicodedata.category(ch)[0] == "L":
            name = unicodedata.name(ch, "")
            if name:
                word = name.split()[0]
                counts["Han (CJK)" if word == "CJK" else word.title()] += 1
    return counts.most_common(1)[0][0] if counts else "Unknown"


def measure(tokenizer: Tokenizer) -> list[LanguageResult]:
    from babel import Locale

    from hfai.data.sources import _cldr_text, cldr_locales

    results = []
    for code in cldr_locales():
        locale = Locale.parse(code)
        text = _cldr_text(locale, "eval")
        if not text:
            continue
        ids = tokenizer.encode(text)
        results.append(LanguageResult(code, locale.display_name or code, dominant_script(text),
                                      len(text), len(ids), tokenizer.decode(ids) == text))
    return results


def markdown(results: list[LanguageResult], title: str, tokenizer: Tokenizer) -> str:
    by_script: dict[str, list[LanguageResult]] = defaultdict(list)
    for result in results:
        by_script[result.script].append(result)
    training = tokenizer.meta.get("training", {})
    lines = [
        f"# Tokenizer coverage: {title}",
        "",
        f"Tokenizer fingerprint `{tokenizer.fingerprint[:16]}`, vocabulary {tokenizer.vocab_size}, "
        f"trained on {training.get('bytes', 0):,} bytes from: {', '.join(training.get('sources', [])) or 'unknown'}.",
        "",
        "Measured on held-out Unicode CLDR word lists (names of scripts, months and days, in each language's own words). "
        "These are word lists, not running text: they show coverage of writing systems, not understanding. "
        "Characters per token: higher is more efficient; about 1 or below means the text is being spelled out byte by byte.",
        "",
        f"**Round trip (coverage level L0): {sum(r.round_trip for r in results)} of {len(results)} languages pass.**",
        "",
        "## By writing system",
        "",
        "| Script | Languages | Round trip | Characters per token (median) |",
        "|---|---|---|---|",
    ]
    for script, group in sorted(by_script.items(), key=lambda item: (-len(item[1]), item[0])):
        ratios = sorted(r.chars_per_token for r in group)
        median = ratios[len(ratios) // 2]
        lines.append(f"| {script} | {len(group)} | {sum(r.round_trip for r in group)}/{len(group)} | {median:.2f} |")
    lines += ["", "## Every language", "", "<details><summary>Show all languages</summary>", "",
              "| Code | Language | Script | Round trip | Characters per token |", "|---|---|---|---|---|"]
    for r in sorted(results, key=lambda r: r.code):
        lines.append(f"| {r.code} | {r.name} | {r.script} | {'yes' if r.round_trip else '**NO**'} | {r.chars_per_token:.2f} |")
    lines += ["", "</details>", ""]
    return "\n".join(lines)
