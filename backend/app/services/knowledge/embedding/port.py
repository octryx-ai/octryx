"""The ``Embedder`` port: bounded input, validated vectors, fixed failure states.

Every adapter returns exactly one vector per input, of the space's dimension, made of finite
floats. Anything else is a contract violation, never a partially usable answer. Failures carry a
closed state and a fixed reason token; no provider message, request or credential text is kept.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .catalog import EmbeddingSpace

MAX_BATCH_TEXTS = 64


class EmbeddingPurpose(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


class EmbeddingState(StrEnum):
    NEEDS_CONFIGURATION = "needs_configuration"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    CONTRACT_VIOLATION = "contract_violation"
    LIMIT_EXCEEDED = "limit_exceeded"


class EmbeddingError(Exception):
    """A closed embedding failure. ``reason`` is a fixed lower-case token."""

    def __init__(self, state: EmbeddingState, reason: str) -> None:
        super().__init__(f"{state.value}:{reason}")
        self.state = state
        self.reason = reason


class Embedder(Protocol):
    space: EmbeddingSpace

    async def embed(self, texts: list[str], purpose: EmbeddingPurpose) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class EmbeddingRuntime:
    """The Instance's embedding space and the adapter that serves it."""

    space: EmbeddingSpace
    embedder: Embedder


def checked_inputs(space: EmbeddingSpace, texts: object, purpose: object) -> list[str]:
    """The texts to embed, prefixed for the space; refuses anything unbounded or untyped."""
    if type(purpose) is not EmbeddingPurpose:
        raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "purpose")
    if type(texts) is not list or not 0 < len(texts) <= MAX_BATCH_TEXTS:
        raise EmbeddingError(EmbeddingState.LIMIT_EXCEEDED, "batch")
    prefix = space.query_prefix if purpose is EmbeddingPurpose.QUERY else space.document_prefix
    prepared = []
    for text in texts:
        if type(text) is not str or not text.strip():
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "text")
        if len(text) > space.max_input_chars:
            raise EmbeddingError(EmbeddingState.LIMIT_EXCEEDED, "text_length")
        prepared.append(prefix + text)
    return prepared


def checked_vectors(space: EmbeddingSpace, vectors: object, expected: int) -> list[list[float]]:
    """Exactly ``expected`` vectors of the space's dimension, as plain finite floats."""
    if type(vectors) is not list or len(vectors) != expected:
        raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "vector_count")
    checked: list[list[float]] = []
    for vector in vectors:
        try:
            values = [float(value) for value in vector] if isinstance(vector, list | tuple) else None
        except (TypeError, ValueError):
            values = None
        if values is None or len(values) != space.dimensions or not all(math.isfinite(v) for v in values):
            raise EmbeddingError(EmbeddingState.CONTRACT_VIOLATION, "vector_shape")
        checked.append(values)
    return checked


__all__ = [
    "MAX_BATCH_TEXTS",
    "Embedder",
    "EmbeddingError",
    "EmbeddingPurpose",
    "EmbeddingRuntime",
    "EmbeddingState",
    "checked_inputs",
    "checked_vectors",
]
