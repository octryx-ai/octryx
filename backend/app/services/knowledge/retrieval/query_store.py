"""The narrow query-store boundary behind Knowledge retrieval.

A ``KnowledgeQueryStore`` is private trusted infrastructure, never a
model-visible tool. It receives only a validated :class:`RetrievalRequest` and
returns product :class:`Evidence`. Sessions, ORM rows, SQL, Cypher, database
record ids, database names, and credentials stay inside the implementation.

Implementations must:

- define all three methods as ``async def`` (the facade verifies this);
- scope every search to ``request.workspace`` and nothing else, and return
  only evidence whose ``workspace`` is that Workspace;
- return at most ``request.limit_per_mode`` items, all tagged with the mode
  that was called;
- treat ``request.query_text`` as ranking data, never as query-language text;
- raise :class:`~app.services.knowledge.errors.KnowledgeIndexUnavailableError`
  when the index for that mode cannot serve the request (or cannot serve it
  completely), instead of returning an empty or short result that would look
  like "nothing found".

Any other exception a store raises is converted by the facade into a fixed
``KnowledgeStoreContractError``; store messages never reach callers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .contracts import Evidence, RetrievalRequest


@runtime_checkable
class KnowledgeQueryStore(Protocol):
    async def search_lexical(self, request: RetrievalRequest) -> Sequence[Evidence]:
        """Term-based retrieval over Workspace passages."""
        ...

    async def search_vector(self, request: RetrievalRequest) -> Sequence[Evidence]:
        """Embedding-similarity retrieval; the store owns query embedding."""
        ...

    async def search_graph(self, request: RetrievalRequest) -> Sequence[Evidence]:
        """Entity and relation retrieval over the Workspace knowledge graph."""
        ...
