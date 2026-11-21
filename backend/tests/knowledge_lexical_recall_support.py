"""Shared corpus, prepared-workspace and request helpers for the bounded lexical recall tests."""

from __future__ import annotations

from app.services.knowledge.identity.workspace import WorkspaceId
from app.services.knowledge.ingestion.spans import derive_evidence_key
from app.services.knowledge.retrieval.contracts import RetrievalMode, RetrievalRequest
from tests.knowledge_evidence_seed_support import new_workspace_id

# Two source revisions, so the best spans really do sort last: the evidence key is
# ``<revision_id_hex>:<span_ordinal>`` and these hex forms differ in their first
# character.
COMMON_REVISION = "0a000000-0000-4000-8000-000000000000"


BEST_REVISION = "ff000000-0000-4000-8000-000000000000"


# limit_per_mode 16 makes the cap exactly MAX_CANDIDATES, so the fixtures below
# exercise the real upper bound rather than a smaller derived one.
LIMIT = 16


FILLER_PER_TERM = 70


def _workspace() -> WorkspaceId:
    return WorkspaceId.parse(new_workspace_id())


def _corpus(best: tuple[str, ...]) -> dict[str, str]:
    """70 ``alpha``-only spans, 70 ``beta``-only spans, and the best spans keyed last."""
    spans: dict[str, str] = {}
    ordinal = 0
    for term in ("alpha", "beta"):
        for index in range(FILLER_PER_TERM):
            ordinal += 1
            spans[derive_evidence_key(COMMON_REVISION, ordinal)] = f"{term} filler token {index}"
    for index, body in enumerate(best, start=1):
        spans[derive_evidence_key(BEST_REVISION, index)] = body
    return spans


def _request(workspace: WorkspaceId, query_text: str, *, limit: int = LIMIT) -> RetrievalRequest:
    return RetrievalRequest(
        workspace=workspace,
        query_text=query_text,
        modes=frozenset({RetrievalMode.LEXICAL}),
        limit_per_mode=limit,
    )
