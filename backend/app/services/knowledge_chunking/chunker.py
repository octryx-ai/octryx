"""Deterministic document chunking for the naive vector-RAG layer."""

from __future__ import annotations

import re
from dataclasses import dataclass

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE = re.compile(r"[ \t]+")


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    token_count: int


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _normalize(text: str) -> str:
    lines = [_WHITESPACE.sub(" ", line).strip() for line in (text or "").splitlines()]
    return "\n".join(lines).strip()


def _split_units(text: str, max_tokens: int) -> list[str]:
    units: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if estimate_tokens(paragraph) <= max_tokens:
            units.append(paragraph)
            continue
        for sentence in _SENTENCE_SPLIT.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if estimate_tokens(sentence) <= max_tokens:
                units.append(sentence)
                continue
            words = sentence.split(" ")
            window = max(1, max_tokens * 4 // 6)  # ~max_tokens worth of words
            for start in range(0, len(words), window):
                chunk_words = words[start : start + window]
                if chunk_words:
                    units.append(" ".join(chunk_words))
    return units


def _overlap_tail(text: str, overlap_tokens: int) -> str:
    if overlap_tokens <= 0:
        return ""
    words = text.split(" ")
    tail = words[-(overlap_tokens * 4 // 6 or 1) :]
    return " ".join(tail).strip()


def chunk_document(
    text: str,
    *,
    max_tokens: int = 350,
    overlap_tokens: int = 50,
) -> list[TextChunk]:
    normalized = _normalize(text)
    if not normalized:
        return []
    units = _split_units(normalized, max_tokens)
    if not units:
        return []

    chunks: list[TextChunk] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush() -> str:
        nonlocal buffer, buffer_tokens
        body = "\n".join(buffer).strip()
        if body:
            chunks.append(TextChunk(index=len(chunks), text=body, token_count=estimate_tokens(body)))
        buffer, buffer_tokens = [], 0
        return body

    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if buffer and buffer_tokens + unit_tokens > max_tokens:
            body = flush()
            overlap = _overlap_tail(body, overlap_tokens)
            if overlap:
                buffer.append(overlap)
                buffer_tokens += estimate_tokens(overlap)
        buffer.append(unit)
        buffer_tokens += unit_tokens
    flush()
    return chunks
