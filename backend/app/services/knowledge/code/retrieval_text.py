"""What a code span is searched by: its file, its symbol, and the words of its identifiers. Derived only from the span
and its locator, and never cited."""

from __future__ import annotations

import re

MAX_WORDS = 160
# An identifier as written: word characters joined by dots (``javax.cache.Caching``).
_IDENTIFIER = re.compile(r"[^\W_][\w]*(?:\.[^\W_][\w]*)*", re.UNICODE)
# CamelCase boundaries: ``HTTPServer`` -> HTTP, Server; ``initCreationForm`` -> init, Creation, Form.
_CAMEL_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", re.UNICODE)
_SEPARATORS = re.compile(r"[._\-/\\$]+")


def identifier_words(identifier: str) -> list[str]:
    words: list[str] = []
    for segment in _SEPARATORS.split(identifier):
        if not segment:
            continue
        parts = _CAMEL_PART.findall(segment)
        words.extend(part.lower() for part in (parts or [segment]))
    return words


def _words_of(text: str) -> list[str]:
    found: list[str] = []
    for match in _IDENTIFIER.finditer(text):
        identifier = match.group(0)
        words = identifier_words(identifier)
        # A plain lower-case word is already a token of the text; only compound identifiers add words.
        if len(words) > 1 or (words and words[0] != identifier.lower()):
            found.extend(words)
            found.extend(segment.lower() for segment in identifier.split(".") if "." in identifier)
    return found


def code_context_header(path: str, section_path: tuple[str, ...]) -> str:
    symbol = ".".join(section_path)
    return f"{path} § {symbol}" if symbol else path


def code_retrieval_text(text: str, *, path: str, section_path: tuple[str, ...]) -> str:
    words: dict[str, None] = {}
    for word in [*identifier_words(path), *(w for name in section_path for w in identifier_words(name)),
                 *_words_of(text)]:
        if len(words) >= MAX_WORDS:
            break
        words.setdefault(word, None)
    return f"{code_context_header(path, section_path)}\n{' '.join(words)}\n{text}"


def code_embedding_text(text: str, *, path: str, section_path: tuple[str, ...]) -> str:
    return f"{code_context_header(path, section_path)}\n{text}"


__all__ = [
    "MAX_WORDS",
    "code_context_header",
    "code_embedding_text",
    "code_retrieval_text",
    "identifier_words",
]
