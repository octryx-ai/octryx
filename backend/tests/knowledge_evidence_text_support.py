"""Text helpers of the Knowledge Evidence doubles: the index analyser's tokens, a concept embedder, unfencing."""

from __future__ import annotations

import hashlib
import math
import re

from app.services.knowledge.embedding.port import EmbeddingPurpose

# The word-break rules of the live index's analyser (Lucene ``StandardTokenizer``, Unicode UAX #29),
# as far as they decide which query token matches which body token. Verified against a real index
# (spring-petclinic): ``springframework`` and ``petclinic`` do not match the dotted
# package names of the Java files, ``OwnerController`` is one token, ``/owners/new`` is ``owners``
# and ``new``, ``vet_specialties`` is one token. Unicode-aware: ``Zürich`` is one token, not two.
_WORD = re.compile(r"\w")
_MID_LETTER = frozenset(".:'\u2019")
_MID_NUMBER = frozenset(".,;'\u2019")


def _joins(text: str, index: int) -> bool:
    if index == 0 or index + 1 >= len(text):
        return False
    before, mark, after = text[index - 1], text[index], text[index + 1]
    if before.isdigit() and after.isdigit():
        return mark in _MID_NUMBER
    return mark in _MID_LETTER and before.isalpha() and after.isalpha()


def _tokens(text: object) -> set[str]:
    value = str(text)
    found: set[str] = set()
    start: int | None = None
    for index, char in enumerate(value):
        if _WORD.match(char) or (start is not None and _joins(value, index)):
            start = index if start is None else start
            continue
        if start is not None:
            found.add(value[start:index].lower())
            start = None
    if start is not None:
        found.add(value[start:].lower())
    return found


_CONCEPTS = {"drill": 0, "exercise": 0, "rehearsal": 0, "failover": 1, "switchover": 1, "password": 2, "secret": 2}


class ConceptEmbedder:
    def __init__(self, space) -> None:
        self.space = space
        self.calls: list[tuple[EmbeddingPurpose, int]] = []

    async def embed(self, texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]:
        self.calls.append((purpose, len(texts)))
        vectors = []
        for text in texts:
            vector = [0.0] * self.space.dimensions
            for word in re.findall(r"[a-z]+", text.lower()):
                if word.rstrip("s") in _CONCEPTS or word in _CONCEPTS:
                    vector[_CONCEPTS.get(word, _CONCEPTS.get(word.rstrip("s"), 0))] += 1.0
                else:
                    vector[10 + int(hashlib.sha256(word.encode()).hexdigest(), 16) % (self.space.dimensions - 10)] += (
                        0.1
                    )
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors


_FENCED_TEXT = re.compile(r"\A<<<(?P<label>[^\n]*) (?P<fence>[0-9a-f]{16})>>>\n(?P<body>.*)\n<<<end (?P=label) (?P=fence)>>>\Z",
                          re.DOTALL)


def unfenced(value):
    if isinstance(value, str):
        match = _FENCED_TEXT.match(value)
        return match.group("body") if match else value
    if isinstance(value, dict):
        # The fence's notice (``content_is_data``) is the model-facing path's own field, not the tool's.
        return {key: unfenced(item) for key, item in value.items()
                if not (key == "content_is_data" and isinstance(item, str) and item.startswith("Untrusted data"))}
    if isinstance(value, list):
        return [unfenced(item) for item in value]
    return value
