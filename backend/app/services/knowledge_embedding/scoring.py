from __future__ import annotations

import hashlib
import math
import re

DEFAULT_EMBEDDING_MODEL = "hash-embedding-v1"
EMBEDDING_DIMENSION = 96


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-zA-Z0-9_-]{3,}", value.lower()) if token]


def build_embedding_from_text(text: str, *, dimension: int = EMBEDDING_DIMENSION) -> list[float]:
    vector = [0.0] * max(8, int(dimension))
    for token in _tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % len(vector)
        sign = -1.0 if digest[4] % 2 else 1.0
        weight = 1.0 + (digest[5] % 5) / 10.0
        vector[index] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def compute_semantic_similarity(query_embedding: list[float], entry_embedding: list[float] | None) -> float:
    if not query_embedding or not entry_embedding:
        return 0.0
    # Different dimensions mean different embedding models. An entry not yet
    # reindexed to the current model must not score via length truncation — it
    # simply does not match, so return 0.0 instead of comparing a prefix.
    if len(query_embedding) != len(entry_embedding):
        return 0.0
    dot = sum(float(query_embedding[i]) * float(entry_embedding[i]) for i in range(len(query_embedding)))
    return max(0.0, min(1.0, (dot + 1.0) / 2.0))
