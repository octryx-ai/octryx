"""Graphiti's embedder and cross-encoder, bound to the platform's own."""

from __future__ import annotations

from collections.abc import Iterable

from ..embedding.port import MAX_BATCH_TEXTS, EmbeddingPurpose, EmbeddingRuntime
from .errors import GraphStoreError, GraphStoreState
from .graphiti_boundary import CrossEncoderClient, EmbedderClient


class WorkspaceEmbedder(EmbedderClient):
    def __init__(self, runtime: EmbeddingRuntime) -> None:
        self._runtime = runtime

    async def create(self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]) -> list[float]:
        # Graphiti passes one text, or a list whose first text is the one it wants embedded (the
        # contract of its OpenAI embedder); token ids are never accepted.
        if isinstance(input_data, list) and input_data and all(isinstance(item, str) for item in input_data):
            input_data = input_data[0]
        if not isinstance(input_data, str) or not input_data:
            raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)
        return (await self._runtime.embedder.embed([input_data], EmbeddingPurpose.DOCUMENT))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(input_data_list), MAX_BATCH_TEXTS):
            batch = input_data_list[start : start + MAX_BATCH_TEXTS]
            vectors.extend(await self._runtime.embedder.embed(batch, EmbeddingPurpose.DOCUMENT))
        return vectors


class RefusingCrossEncoder(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        raise GraphStoreError(GraphStoreState.CONTRACT_VIOLATION)


__all__ = ["RefusingCrossEncoder", "WorkspaceEmbedder"]
