"""Shared workspace ids, unsafe character sets and request/evidence builders for the Knowledge contract tests."""

from __future__ import annotations

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.retrieval.contracts import RetrievalMode, RetrievalRequest

WS = "3f2b8c1e-9a4d-4e7b-8c21-5d6f7a8b9c0d"


def _request(**overrides) -> RetrievalRequest:
    values = {"workspace": WorkspaceId.parse(WS), "query_text": "orders service", "modes": {RetrievalMode.VECTOR}}
    values.update(overrides)
    return RetrievalRequest(**values)


class _SubWorkspace(WorkspaceId):
    __slots__ = ()


class _SneakyStr(str):
    def split(self, *args, **kwargs):  # type: ignore[override]
        return ["ok"]

    def __contains__(self, item):  # type: ignore[override]
        return False
