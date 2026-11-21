"""Reads over a Knowledge scope: the reader's Workspace plus its bound sources.

Each Workspace is still queried on its own, scoped to its own rows of the Evidence index, with its own
authorized view. Nothing is merged at the storage level, so hard isolation stays intact. Only the answers are
combined, deterministically:

- **Search.** Every Workspace in scope answers the hybrid retrieval with the binding's product
  bound. The hits are fused by rank (RRF); when every Workspace was reranked, by the reranker's
  relevance, which is comparable because it is the same model on the same query. The same
  *passage* found in two Workspaces is kept once, from the better-ranked hit: same source
  content digest, same character window and the same span text. Different passages of one document
  are different hits; a hit without a valid locator keeps its own evidence identity and is never
  merged. Each hit names its Workspace.
- **Read.** An evidence key names its revision, so the first Workspace in scope that holds it
  serves the read. A bound source only serves revisions of the binding's products.
- **Changes.** A product's change facts are read from one Workspace: the first in scope order that
  has extracted facts for it (the reader's own first). So a project Workspace answers from a bound
  library Workspace until it holds its own facts for that product.

A Workspace that cannot answer reports its fixed state per Workspace. The reader's own failure
fails the read only when no Workspace in scope answered.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import KnowledgeRevisionScope
from ..access.bindings import KnowledgeScope
from ..ledger.errors import EvidenceLedgerError, EvidenceLedgerState, EvidenceRecordNotFoundError
from ..ledger.reading import SpanWindow, read_span_window
from ..runtime import EvidenceRuntime
from ..sources.scope import normalize_products
from .evidence import DEFAULT_RESULT_LIMIT
from .hybrid import RRF_K, HybridEvidence, hybrid_workspace_evidence
from .stage_timing import measuring

STATE_OUTSIDE_BINDING = "outside_binding_products"


@dataclass(frozen=True, slots=True)
class ScopedHit:
    workspace_id: str
    workspace_name: str
    hit: HybridEvidence


@dataclass(frozen=True, slots=True)
class ScopedRetrieval:
    query_text: str
    limit: int
    evidence: tuple[ScopedHit, ...]
    # Per Workspace: its retrieval modes' states, or {"state": <reason>} when it did not answer.
    workspace_states: dict[str, dict[str, str]] = field(default_factory=dict)
    # Per Workspace: milliseconds per stage of its retrieval (stage_timing.py), ``total`` included.
    workspace_timings: dict[str, dict[str, int]] = field(default_factory=dict)


def _requested(products: object) -> tuple[str, ...]:
    return tuple(normalize_products(products)) if products else ()


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _passage_identity(workspace_id: str, hit: HybridEvidence) -> tuple[str, ...]:
    """Which hits are the same passage.

    ``content_sha256`` is the digest of the whole source revision, so on its own it would merge every
    passage of a document. A passage is that digest plus its validated character window plus the
    exact span text: equal only for the same text at the same place of the same content, whichever
    Workspace or parser produced it (a span ordinal alone is not used). When the digest or the window
    is missing or invalid, the hit keeps its own authenticated evidence identity and merges with
    nothing.
    """
    evidence = hit.evidence
    digest = evidence.content_sha256 if isinstance(evidence.content_sha256, str) else ""
    start, end = evidence.char_start, evidence.char_end
    window_valid = (
        type(start) is int and type(end) is int and 0 <= start < end and isinstance(evidence.text, str)
    )
    if _SHA256_HEX.fullmatch(digest) and window_valid:
        text_digest = hashlib.sha256(evidence.text.encode("utf-8")).hexdigest()
        return ("passage", digest, str(start), str(end), text_digest)
    return ("evidence", workspace_id, str(evidence.evidence_key))


def _fused(lists: list[tuple[str, str, tuple[HybridEvidence, ...]]], *, by_relevance: bool) -> list[ScopedHit]:
    scored: list[tuple[float, int, ScopedHit]] = []
    order = 0
    for workspace_id, name, hits in lists:
        for rank, hit in enumerate(hits, start=1):
            score = (hit.relevance or 0.0) if by_relevance else 1.0 / (RRF_K + rank)
            scored.append((score, order, ScopedHit(workspace_id, name, hit)))
            order += 1
    seen: set[tuple[str, ...]] = set()
    fused: list[ScopedHit] = []
    for _, _, item in sorted(scored, key=lambda entry: (-entry[0], entry[1])):
        identity = _passage_identity(item.workspace_id, item.hit)
        if identity in seen:
            continue
        seen.add(identity)
        fused.append(item)
    return fused


async def scoped_evidence(
    db: AsyncSession,
    *,
    runtime: EvidenceRuntime,
    scope: KnowledgeScope,
    query_text: object,
    limit: int | None = None,
    products: object = None,
    version: object = None,
) -> ScopedRetrieval:
    requested = _requested(products)
    limit = DEFAULT_RESULT_LIMIT if limit is None else limit
    states: dict[str, dict[str, str]] = {project_id: {"state": reason} for project_id, reason in scope.skipped.items()}
    answered: list[tuple[str, str, tuple[HybridEvidence, ...]]] = []
    primary_error: EvidenceLedgerError | None = None
    query = str(query_text or "")
    targets = [(scope.primary, scope.primary_name, requested or None)]
    for source in scope.sources:
        bounded = source.products_for(requested)
        if bounded is None:
            states[source.authorized.project_id] = {"state": STATE_OUTSIDE_BINDING}
            continue
        targets.append((source.authorized, source.name, list(bounded) or None))
    timings: dict[str, dict[str, int]] = {}
    for authorized, name, product_filter in targets:
        timer = None
        try:
            with measuring() as timer:
                result = await hybrid_workspace_evidence(
                    db,
                    runtime=runtime,
                    authorized=authorized,
                    query_text=query_text,
                    limit=limit,
                    products=product_filter,
                    version=version,
                )
        except EvidenceLedgerError as error:
            if error.state is EvidenceLedgerState.INVALID_REQUEST:
                raise
            states[authorized.project_id] = {"state": error.state.value}
            if authorized is scope.primary:
                primary_error = error
            continue
        finally:
            if timer is not None:
                timings[authorized.project_id] = timer.as_dict()
        query = result.query_text
        states[authorized.project_id] = dict(result.mode_states)
        answered.append((authorized.project_id, name, result.evidence))
    if not answered and primary_error is not None:
        raise primary_error
    by_relevance = bool(answered) and all(states[workspace].get("rerank") == "ok" for workspace, _, _ in answered)
    return ScopedRetrieval(query, limit, tuple(_fused(answered, by_relevance=by_relevance)[:limit]), states, timings)


async def _revision_products(db: AsyncSession, project_id: str, evidence_key: str) -> tuple[str, ...]:
    try:
        revision_id = str(uuid.UUID(str(evidence_key).split(":", 1)[0]))
    except ValueError:
        return ()
    products = (
        await db.execute(
            select(KnowledgeRevisionScope.products).where(
                KnowledgeRevisionScope.project_id == project_id, KnowledgeRevisionScope.revision_id == revision_id
            )
        )
    ).scalar_one_or_none()
    return tuple(products or ())


async def scoped_read(
    db: AsyncSession, *, scope: KnowledgeScope, evidence_key: object, window: object
) -> tuple[str, SpanWindow]:
    """``(workspace_id, window)`` from the first Workspace in scope that holds ``evidence_key``."""
    try:
        return scope.primary.project_id, await read_span_window(
            db, authorized=scope.primary, evidence_key=evidence_key, window=window
        )
    except EvidenceRecordNotFoundError:
        pass
    for source in scope.sources:
        try:
            read = await read_span_window(db, authorized=source.authorized, evidence_key=evidence_key, window=window)
        except EvidenceRecordNotFoundError:
            continue
        if source.products and not set(
            await _revision_products(db, source.authorized.project_id, str(evidence_key))
        ) & set(source.products):
            # Outside the binding's products: the same answer as "not here".
            continue
        return source.authorized.project_id, read
    raise EvidenceRecordNotFoundError()


__all__ = ["STATE_OUTSIDE_BINDING", "ScopedHit", "ScopedRetrieval", "scoped_evidence", "scoped_read"]
