"""Hybrid retrieval: lexical and vector evidence, fused into one ranked, cited answer.

Both modes run against the same authorized Workspace and each returns only citable,
current evidence (``retrieve_workspace_evidence``). The candidates are fused by Reciprocal Rank
Fusion: deterministic, model-free, and immune to the two modes scoring on different scales. A hit
found only by vector search must reach the space's ``min_similarity``; below that it is noise, not
evidence.

Lexical retrieval is the baseline: a Workspace that cannot serve it fails the request. Every other
mode reports its own outcome in ``mode_states`` (``needs_configuration``, ``denied``,
``unavailable``, ``contract_violation``), so a lexical-only answer is always marked as such and
never passes silently for the complete one.

The modes run one after the other, because they share the caller's database session.

With a reranker the fused candidates are scored jointly with the query and reordered;
a candidate below the reranker's ``min_relevance`` is dropped. A code hit is scored with its file and
symbol header in front of its lines, so the reranker sees which class a method belongs to.
Rerank is reported in ``mode_states``
like any mode: without one, or when it fails, the fused order stands and the state says why.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_parsing import SPAN_KIND_CODE
from ..access.authorization import AuthorizedWorkspace
from ..code.retrieval_text import code_embedding_text
from ..embedding.port import EmbeddingError, EmbeddingState
from ..embedding.selection import REMOTE_KIND_RERANKER, admit_remote
from ..ledger.errors import EvidenceLedgerError, EvidenceLedgerState, InvalidEvidenceRequestError
from ..rerank.availability import record_rerank_ok, record_rerank_unavailable, rerank_suspended
from ..runtime import EvidenceRuntime
from .contracts import MAX_LIMIT_PER_MODE
from .evidence import (
    DEFAULT_RESULT_LIMIT,
    LEXICAL_MODES,
    MAX_RESULT_LIMIT,
    VECTOR_MODES,
    CitedEvidence,
    retrieve_workspace_evidence,
)
from .stage_timing import timed_stage

RRF_K = 60
# Each mode fetches more than the answer needs, so fusion has candidates to choose from.
CANDIDATE_FACTOR = 3
MODE_OK = "ok"


@dataclass(frozen=True, slots=True)
class HybridEvidence:
    """One fused hit: the cited span, which modes found it, and its fused rank score."""

    evidence: CitedEvidence
    modes: tuple[str, ...]
    fused_score: float
    similarity: float | None
    relevance: float | None = None


@dataclass(frozen=True, slots=True)
class HybridRetrieval:
    workspace_id: str
    query_text: str
    limit: int
    evidence: tuple[HybridEvidence, ...]
    mode_states: dict[str, str]


def _limit(limit: object) -> int:
    if limit is None:
        return DEFAULT_RESULT_LIMIT
    if type(limit) is not int or not 1 <= limit <= MAX_RESULT_LIMIT:
        raise InvalidEvidenceRequestError()
    return limit


async def hybrid_workspace_evidence(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    query_text: object,
    limit: object = None,
    products: object = None,
    version: object = None,
) -> HybridRetrieval:
    """Lexical plus (when available) vector evidence, fused, floored and cut to ``limit``."""
    bounded = _limit(limit)
    candidates = min(bounded * CANDIDATE_FACTOR, MAX_LIMIT_PER_MODE)
    with timed_stage("lexical"):
        lexical = await retrieve_workspace_evidence(
            db,
            runtime=runtime,
            authorized=authorized,
            query_text=query_text,
            limit=candidates,
            modes=LEXICAL_MODES,
            products=products,
            version=version,
        )
    states = {"lexical": MODE_OK}
    vector_hits = await _vector_hits(
        db,
        runtime=runtime,
        authorized=authorized,
        query_text=query_text,
        candidates=candidates,
        products=products,
        version=version,
        states=states,
    )
    floor = runtime.embedding.space.min_similarity if runtime.embedding is not None else 1.0
    ranked = _fused(lexical.evidence, vector_hits, floor)
    ranked = await _reranked(db, runtime, authorized, lexical.query_text, ranked, states)
    return HybridRetrieval(
        workspace_id=lexical.workspace_id,
        query_text=lexical.query_text,
        limit=bounded,
        evidence=tuple(ranked[:bounded]),
        mode_states=states,
    )


async def _vector_hits(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    query_text: object,
    candidates: int,
    products: object,
    version: object,
    states: dict[str, str],
) -> tuple[CitedEvidence, ...]:
    """Vector candidates, or none with the mode's state recorded; only an invalid request fails the search."""
    vector_hits: tuple[CitedEvidence, ...] = ()
    try:
        with timed_stage("vector"):
            vector = await retrieve_workspace_evidence(
                db,
                runtime=runtime,
                authorized=authorized,
                query_text=query_text,
                limit=candidates,
                modes=VECTOR_MODES,
                products=products,
                version=version,
            )
        vector_hits = vector.evidence
        states["vector"] = MODE_OK
    except EvidenceLedgerError as error:
        if error.state is EvidenceLedgerState.INVALID_REQUEST:
            raise
        states["vector"] = error.state.value
    return vector_hits


def _fused(
    lexical_hits: tuple[CitedEvidence, ...], vector_hits: tuple[CitedEvidence, ...], floor: float
) -> list[HybridEvidence]:
    """Reciprocal Rank Fusion of both modes; a vector-only hit must reach the similarity floor."""
    fused: dict[str, HybridEvidence] = {}
    for rank, item in enumerate(lexical_hits, start=1):
        fused[item.evidence_key] = HybridEvidence(item, ("lexical",), 1.0 / (RRF_K + rank), None)
    for rank, item in enumerate(vector_hits, start=1):
        similarity = item.score if item.score is not None else 0.0
        known = fused.get(item.evidence_key)
        if known is not None:
            fused[item.evidence_key] = replace(
                known,
                modes=("lexical", "vector"),
                fused_score=known.fused_score + 1.0 / (RRF_K + rank),
                similarity=similarity,
            )
        elif similarity >= floor:
            fused[item.evidence_key] = HybridEvidence(item, ("vector",), 1.0 / (RRF_K + rank), similarity)
    return sorted(fused.values(), key=lambda hit: (-hit.fused_score, hit.evidence.evidence_key))


async def _reranked(
    db: AsyncSession,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    query_text: str,
    ranked: list[HybridEvidence],
    states: dict[str, str],
) -> list[HybridEvidence]:
    """Reorder by the reranker's relevance and drop what falls below its floor; else keep ``ranked``."""
    if runtime.reranker is None:
        states["rerank"] = "needs_configuration"
        return ranked
    if not ranked:
        states["rerank"] = MODE_OK
        return ranked
    spec = runtime.reranker.spec
    if rerank_suspended(spec.key):
        # It failed moments ago (rerank/availability.py): the same visible state, without waiting for it again.
        states["rerank"] = EmbeddingState.UNAVAILABLE.value
        return ranked
    candidates = ranked[: spec.max_documents]
    try:
        await admit_remote(
            db, project_id=authorized.admission_project_id, data_policy_class=spec.data_policy_class,
            model_kind=REMOTE_KIND_RERANKER,
        )
        with timed_stage("rerank"):
            scores = await runtime.reranker.reranker.rerank(
                query_text, [_rerank_document(hit.evidence) for hit in candidates]
            )
    except EmbeddingError as error:
        if error.state is EmbeddingState.UNAVAILABLE:
            record_rerank_unavailable(spec.key)
        states["rerank"] = error.state.value
        return ranked
    record_rerank_ok(spec.key)
    states["rerank"] = MODE_OK
    return [
        replace(candidates[score.index], relevance=score.relevance)
        for score in scores
        if score.relevance >= spec.min_relevance
    ]


def _rerank_document(evidence: CitedEvidence) -> str:
    """A code hit is reranked with its file and symbol header, the way it is embedded."""
    if evidence.kind == SPAN_KIND_CODE:
        return code_embedding_text(evidence.text, path=evidence.source_title, section_path=evidence.section_path)
    return evidence.text


__all__ = ["HybridEvidence", "HybridRetrieval", "hybrid_workspace_evidence"]
