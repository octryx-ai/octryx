"""Repair words a PDF hyphenated across lines inside table cells. A break is joined only when the joined word occurs
elsewhere in the document."""

from __future__ import annotations

import re
from collections.abc import Iterable

_BREAK = re.compile(r"([a-z]+)[-­\u0002]\s+([a-z]+)")
_WORD = re.compile(r"[A-Za-z]+")
_HYPHENS = str.maketrans({"­": "-", "\u0002": "-"})


def document_vocabulary(texts: Iterable[str]) -> frozenset[str]:
    return frozenset(word.lower() for text in texts for word in _WORD.findall(text))


def repair_hyphen_breaks(text: str, vocabulary: frozenset[str]) -> str:
    def join(match: re.Match[str]) -> str:
        head, tail = match.group(1), match.group(2)
        joined = f"{head}{tail}"
        return joined if joined.lower() in vocabulary else f"{head}-{tail}"

    return _BREAK.sub(join, text).translate(_HYPHENS)


__all__ = ["document_vocabulary", "repair_hyphen_breaks"]
