"""Governed, bounded retrieval whose citations resolve back to PostgreSQL. Unresolved keys are dropped; there is no
fallback to another retrieval path."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..access.authorization import AuthorizedWorkspace
from ..embedding.port import EmbeddingError, EmbeddingState
from ..embedding.selection import admit_space
from ..ledger.citations import resolve_citations
from ..ledger.errors import (
    EmbeddingSpaceDeniedError,
    EvidenceLedgerContractError,
    EvidenceStoreNotConfiguredError,
    EvidenceStoreUnavailableError,
    InvalidEvidenceRequestError,
    WorkspaceNotAccessibleError,
)
from ..projection.acl_marker import acl_marker_current
from ..projection.vector_spaces import vector_space_ready
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products, normalize_version
from ..text_safety import remove_unsafe_chars
from .contracts import DEFAULT_LIMIT_PER_MODE, MAX_LIMIT_PER_MODE, RetrievalBundle, RetrievalMode, RetrievalRequest
from .errors import (
    InvalidRetrievalRequestError,
    KnowledgeIndexUnavailableError,
    KnowledgeRetrievalError,
    KnowledgeStoreContractError,
    KnowledgeStoreNotConfiguredError,
    WorkspaceScopeError,
)
from .facade import retrieve_bundle
from .readiness import unprojected_workspace_error
from .stage_timing import timed_stage

logger = logging.getLogger(__name__)

DEFAULT_RESULT_LIMIT = DEFAULT_LIMIT_PER_MODE
MAX_RESULT_LIMIT = MAX_LIMIT_PER_MODE
LEXICAL_MODES = frozenset({RetrievalMode.LEXICAL})
VECTOR_MODES = frozenset({RetrievalMode.VECTOR})


@dataclass(frozen=True, slots=True)
class CitedEvidence:
    evidence_key: str
    text: str
    citation: str
    revision_id: str
    span_ordinal: int
    content_sha256: str
    source_title: str
    source_url: str | None
    # Vector mode: cosine similarity in the Instance's embedding space. Lexical: none published.
    score: float | None = None
    # Structured locator.
    source_id: str = ""
    revision_ordinal: int = 0
    char_start: int = 0
    char_end: int = 0
    products: tuple[str, ...] = ()
    version: str | None = None
    kind: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: tuple[str, ...] = ()
    line_start: int | None = None
    line_end: int | None = None


@dataclass(frozen=True, slots=True)
class EvidenceRetrieval:
    workspace_id: str
    query_text: str
    limit: int
    evidence: tuple[CitedEvidence, ...]
    dropped_unresolved: int


def _mapped_failure(error: KnowledgeRetrievalError) -> Exception:
    if isinstance(error, WorkspaceScopeError):
        return WorkspaceNotAccessibleError()
    if isinstance(error, InvalidRetrievalRequestError):
        return InvalidEvidenceRequestError()
    if isinstance(error, KnowledgeStoreNotConfiguredError):
        return EvidenceStoreNotConfiguredError()
    if isinstance(error, KnowledgeIndexUnavailableError):
        return EvidenceStoreUnavailableError()
    if isinstance(error, KnowledgeStoreContractError):
        return EvidenceLedgerContractError()
    return EvidenceLedgerContractError()


def _validated_limit(limit: object) -> int:
    if limit is None:
        return DEFAULT_RESULT_LIMIT
    if type(limit) is not int or not 1 <= limit <= MAX_RESULT_LIMIT:
        raise InvalidEvidenceRequestError()
    return limit


async def retrieve_workspace_evidence(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    authorized: AuthorizedWorkspace,
    query_text: object,
    limit: object = None,
    modes: frozenset[RetrievalMode] = LEXICAL_MODES,
    products: object = None,
    version: object = None,
) -> EvidenceRetrieval:
    # One mode per request: the facade refuses the same evidence key twice in one bundle.
    if type(runtime) is not EvidenceRuntime or type(authorized) is not AuthorizedWorkspace:
        raise EvidenceLedgerContractError()
    if modes not in (LEXICAL_MODES, VECTOR_MODES):
        raise InvalidEvidenceRequestError()
    bounded_limit = _validated_limit(limit)
    if modes == VECTOR_MODES:
        await _admit_vector_mode(db, runtime, authorized)

    # Never projected (no ACL marker recorded yet): an explicit no_sources / projection_pending
    # state, never an empty result that would read as "nothing found", and never
    # needs_configuration for a healthy instance.
    if not await acl_marker_current(db, authorized.project_id):
        raise await unprojected_workspace_error(db, authorized.project_id)

    request = _request(
        authorized, query_text, bounded_limit, modes, normalize_products(products), normalize_version(version)
    )
    bundle = await _bundle(runtime, request)

    keys = tuple(item.evidence_id for item in bundle.evidence)
    # Re-checked in the ledger too: a stale projection marker never widens access.
    with timed_stage("resolve"):
        resolved = await resolve_citations(db, authorized.project_id, keys, principal_keys=authorized.principal_keys)
    cited = _cited_evidence(bundle, resolved)
    dropped = len(bundle.evidence) - len(cited)
    if dropped:
        logger.warning(
            "Knowledge evidence dropped unresolved projection rows: count=%d workspace=%s",
            dropped,
            authorized.project_id,
        )
    return EvidenceRetrieval(
        workspace_id=authorized.project_id,
        query_text=request.query_text,
        limit=bounded_limit,
        evidence=tuple(cited),
        dropped_unresolved=dropped,
    )


def _cited_evidence(bundle: RetrievalBundle, resolved: dict) -> list[CitedEvidence]:
    cited: list[CitedEvidence] = []
    for item in bundle.evidence:
        citation = resolved.get(item.evidence_id)
        if citation is None:
            continue
        cited.append(
            CitedEvidence(
                evidence_key=item.evidence_id,
                # The ledger's span text: what the projection indexed may be more (a code span's
                # retrieval text), what a hit quotes and cites is exactly the span.
                text=remove_unsafe_chars(citation.text, allow_line_breaks=True).strip(),
                citation=citation.citation,
                revision_id=citation.revision_id,
                span_ordinal=citation.span_ordinal,
                content_sha256=citation.content_sha256,
                source_title=citation.source_title,
                source_url=citation.source_url,
                score=item.score,
                source_id=citation.source_id,
                revision_ordinal=citation.revision_ordinal,
                char_start=citation.char_start,
                char_end=citation.char_end,
                products=citation.products,
                version=citation.version,
                kind=citation.kind,
                page_start=citation.page_start,
                page_end=citation.page_end,
                section_path=citation.section_path,
                line_start=citation.line_start,
                line_end=citation.line_end,
            )
        )
    return cited


async def _admit_vector_mode(db: AsyncSession, runtime: EvidenceRuntime, authorized: AuthorizedWorkspace) -> None:
    if runtime.embedding is None:
        raise EvidenceStoreNotConfiguredError()
    if not await vector_space_ready(db, authorized.project_id, runtime.embedding.space.key):
        # No vectors in this space yet (never embedded, or the Instance switched spaces): an
        # explicit state, answered by an embedding backfill, not an empty or failed search.
        raise EvidenceStoreNotConfiguredError()
    failure: Exception | None = None
    try:
        await admit_space(db, project_id=authorized.admission_project_id, space=runtime.embedding.space)
    except EmbeddingError as error:
        failure = (
            EmbeddingSpaceDeniedError() if error.state is EmbeddingState.DENIED else EvidenceStoreNotConfiguredError()
        )
    if failure is not None:
        raise failure


def _request(
    authorized: AuthorizedWorkspace,
    query_text: object,
    limit: int,
    modes: frozenset[RetrievalMode],
    products: tuple[str, ...] = (),
    version: str | None = None,
) -> RetrievalRequest:
    failure: Exception | None = None
    try:
        return RetrievalRequest(
            workspace=authorized.workspace,
            query_text=query_text,  # type: ignore[arg-type]
            modes=modes,
            limit_per_mode=limit,
            products=products,
            version=version,
            acl_keys=authorized.acl_keys,
        )
    except KnowledgeRetrievalError as error:
        failure = _mapped_failure(error)
    raise failure


async def _bundle(runtime: EvidenceRuntime, request: RetrievalRequest) -> RetrievalBundle:
    failure: Exception | None = None
    try:
        return await retrieve_bundle(runtime.query_store, request)
    except KnowledgeRetrievalError as error:
        failure = _mapped_failure(error)
    # Raised outside the handler so no retrieval error is chained as context.
    raise failure
