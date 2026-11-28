"""The narrow query-store boundary behind Knowledge retrieval. Private trusted infrastructure, never a model-visible
tool."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .contracts import Evidence, RetrievalRequest


@runtime_checkable
class KnowledgeQueryStore(Protocol):
    async def search_lexical(self, request: RetrievalRequest) -> Sequence[Evidence]:
        ...

    async def search_vector(self, request: RetrievalRequest) -> Sequence[Evidence]:
        ...

    async def search_graph(self, request: RetrievalRequest) -> Sequence[Evidence]:
        ...
