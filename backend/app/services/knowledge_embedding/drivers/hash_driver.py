"""Deterministic SHA256 token-hash embedding driver.

Explicit, non-semantic, offline/dev only. This is selected only when the
configured provider is ``local_hash`` — it is never a silent fallback for a
misconfigured real provider.
"""

from __future__ import annotations

from ..scoring import build_embedding_from_text
from .base import FAMILY_LOCAL_HASH, BaseEmbeddingDriver


class HashEmbeddingDriver(BaseEmbeddingDriver):
    provider_id = FAMILY_LOCAL_HASH

    def __init__(self, *, model: str, version: str) -> None:
        self.model = model
        self.version = version

    def embed(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        return [build_embedding_from_text(text) for text in texts]
