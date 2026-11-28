"""Keeps only what the passages back: a sentence without a citation, or citing a number outside the
passages, is dropped; when nothing is left the answer is ``no_answer``."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

_MAX_SENTENCES = 3
_MAX_SENTENCE_CHARS = 600
# Inline markers a model writes into the text anyway ("… is 16 [1][2].", "[1, 3]"). They number the passages of the
# prompt, not the hits on the page, so they are removed; the citations are the ``cites`` list.
_INLINE_MARKERS = re.compile(r"\s*(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])+")


def plain_sentence(text: str) -> str:
    return re.sub(r"\s+([.,;:!?])", r"\1", _INLINE_MARKERS.sub("", text)).strip()


def cited_sentences(answer: dict[str, Any], keys: Sequence[str]) -> list[dict[str, Any]]:
    if answer.get("insufficient") is True:
        return []
    raw = answer.get("sentences")
    if not isinstance(raw, list):
        return []
    sentences: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        cites = entry.get("cites")
        if not isinstance(text, str) or not text.strip() or not isinstance(cites, list):
            continue
        numbers = [number for number in cites if isinstance(number, int) and not isinstance(number, bool)]
        if not numbers or any(number < 1 or number > len(keys) for number in numbers):
            continue
        plain = plain_sentence(text)
        if not plain:
            continue
        cited = list(dict.fromkeys(keys[number - 1] for number in numbers))
        sentences.append({"text": plain[:_MAX_SENTENCE_CHARS], "cites": cited})
        if len(sentences) == _MAX_SENTENCES:
            break
    return sentences


__all__ = ["cited_sentences", "plain_sentence"]
