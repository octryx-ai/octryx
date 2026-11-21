"""What a code span is searched by: its file, its symbol, and the words of its identifiers.

A code span is cited by its own lines, but it is *found* by more than those lines say. The bare
lines are not enough for the Workspace index, whose analyser keeps ``initCreationForm``, ``OwnerController.java`` and
``org.springframework.cache.annotation.EnableCaching`` as single tokens:

- "owner creation" could not reach ``initCreationForm``, nor "caching" ``@EnableCaching``;
- a method span did not say which class or file it belongs to, so "which class handles ..." found
  the method but not its class;
- the path a citation shows (``src/main/java/.../owner/OwnerController.java``) took no part in
  search at all.

So the projection indexes, and the embedding space embeds, a **retrieval text** for every code span:
a header with the file path and the symbol path, a line with the identifier words of the path, the
symbol and the span (CamelCase, snake_case, kebab-case and dotted names split into their words), and
then the span's lines unchanged. It is derived only from the span and its own locator, never from
other content, and it is never cited: the evidence text a hit returns is read back from the ledger
(``retrieval/evidence.py``), so a citation still quotes exactly the repository's lines.

Deterministic: the same span always yields the same retrieval text. Bounded: the word line holds at
most ``MAX_WORDS`` distinct words.
"""

from __future__ import annotations

import re

MAX_WORDS = 160
# An identifier as written: word characters joined by dots (``javax.cache.Caching``).
_IDENTIFIER = re.compile(r"[^\W_][\w]*(?:\.[^\W_][\w]*)*", re.UNICODE)
# CamelCase boundaries: ``HTTPServer`` -> HTTP, Server; ``initCreationForm`` -> init, Creation, Form.
_CAMEL_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", re.UNICODE)
_SEPARATORS = re.compile(r"[._\-/\\$]+")


def identifier_words(identifier: str) -> list[str]:
    """The lower-cased words of one identifier, in order (``EnableCaching`` -> enable, caching)."""
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
    """``<path> § <Outer.inner>``: the file and symbol a code span belongs to."""
    symbol = ".".join(section_path)
    return f"{path} § {symbol}" if symbol else path


def code_retrieval_text(text: str, *, path: str, section_path: tuple[str, ...]) -> str:
    """The indexed form of one code span: header, identifier words, then the span's lines."""
    words: dict[str, None] = {}
    for word in [*identifier_words(path), *(w for name in section_path for w in identifier_words(name)),
                 *_words_of(text)]:
        if len(words) >= MAX_WORDS:
            break
        words.setdefault(word, None)
    return f"{code_context_header(path, section_path)}\n{' '.join(words)}\n{text}"


def code_embedding_text(text: str, *, path: str, section_path: tuple[str, ...]) -> str:
    """The embedded form of one code span: the header, then the span's lines."""
    return f"{code_context_header(path, section_path)}\n{text}"


__all__ = [
    "MAX_WORDS",
    "code_context_header",
    "code_embedding_text",
    "code_retrieval_text",
    "identifier_words",
]
