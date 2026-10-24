"""Split text into chunks before byte-pair encoding.

The tokenizer never merges across chunk boundaries, so chunks decide what a
token *can* be. The rules here are deliberately simple and the same for every
language:

* runs of letters (including combining marks, so Devanagari, Arabic, Thai and
  others stay whole), at most MAX_RUN characters long;
* runs of 1-3 digits;
* runs of other symbols (punctuation, emoji, ...), at most MAX_RUN long;
* whitespace, where a single space attaches to the start of the next word.

There are no English-specific rules (such as for "'s" or "n't").

Joining the chunks always gives back the exact original text; tests check
this on every script.

Character classes come from Python's Unicode database, whose version is
recorded with each trained tokenizer.
"""

from __future__ import annotations

import functools
import re
import unicodedata

MAX_RUN = 24  # long runs (for example in languages written without spaces) are cut into pieces


def _class(ranges: list[tuple[int, int]]) -> str:
    parts = []
    for start, end in ranges:
        parts.append(f"\\U{start:08x}" if start == end else f"\\U{start:08x}-\\U{end:08x}")
    return "".join(parts)


@functools.lru_cache(maxsize=1)
def _pattern() -> re.Pattern:
    letters: list[tuple[int, int]] = []
    numbers: list[tuple[int, int]] = []

    def add(ranges, cp):
        if ranges and ranges[-1][1] == cp - 1:
            ranges[-1] = (ranges[-1][0], cp)
        else:
            ranges.append((cp, cp))

    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        major = unicodedata.category(chr(cp))[0]
        if major in ("L", "M"):
            add(letters, cp)
        elif major == "N":
            add(numbers, cp)
    lm, n = _class(letters), _class(numbers)
    return re.compile(
        rf" ?[{lm}]{{1,{MAX_RUN}}}"
        rf"| ?[{n}]{{1,3}}"
        rf"| ?[^\s{lm}{n}]{{1,{MAX_RUN}}}"
        rf"|\s+(?!\S)"
        rf"|\s+"
    )


def pretokenize(text: str) -> list[str]:
    """Split text into chunks. ``"".join(pretokenize(t)) == t`` always holds."""
    return _pattern().findall(text)


def unicode_version() -> str:
    return unicodedata.unidata_version
