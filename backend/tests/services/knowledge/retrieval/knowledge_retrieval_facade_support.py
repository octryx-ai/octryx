"""Shared helpers for the test_knowledge_retrieval_facade_* modules."""

from __future__ import annotations

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.retrieval.contracts import Evidence, EvidenceKind, RetrievalMode, RetrievalRequest
from app.services.knowledge.retrieval.errors import KnowledgeIndexUnavailableError

WS = WorkspaceId.parse("3f2b8c1e-9a4d-4e7b-8c21-5d6f7a8b9c0d")


OTHER_WS = WorkspaceId.parse("9c0d5d6f-7a8b-4e7b-8c21-3f2b8c1e9a4d")


class FakeStore:
    def __init__(self, results=None, unavailable: frozenset[RetrievalMode] = frozenset(), raises=None) -> None:
        self.results = results or {}
        self.unavailable = unavailable
        self.raises = raises or {}
        self.calls: list[tuple[RetrievalMode, RetrievalRequest]] = []

    async def _search(self, mode: RetrievalMode, request: RetrievalRequest):
        self.calls.append((mode, request))
        if mode in self.unavailable:
            raise KnowledgeIndexUnavailableError(mode.value)
        if mode in self.raises:
            raise self.raises[mode]
        return self.results.get(mode, [])

    async def search_lexical(self, request):
        return await self._search(RetrievalMode.LEXICAL, request)

    async def search_vector(self, request):
        return await self._search(RetrievalMode.VECTOR, request)

    async def search_graph(self, request):
        return await self._search(RetrievalMode.GRAPH, request)


def _request(modes, limit: int = 3) -> RetrievalRequest:
    return RetrievalRequest(workspace=WS, query_text="orders service", modes=frozenset(modes), limit_per_mode=limit)


def _evidence(
    evidence_id: str, mode: RetrievalMode, kind: EvidenceKind = EvidenceKind.PASSAGE, workspace: WorkspaceId = WS
) -> Evidence:
    return Evidence(
        workspace=workspace, evidence_id=evidence_id, mode=mode, kind=kind, text=f"text {evidence_id}", score=0.5
    )


def _assert_closed(exc: BaseException) -> None:
    assert str(exc) == type(exc).default_message
    assert exc.__cause__ is None and exc.__context__ is None
    assert "SELECT" not in repr(exc) and "orders" not in repr(exc)
