"""Workspace Knowledge search and passage windows (split from ``knowledge_evidence_sources.py``).

Transport only: authenticate, read the request, delegate to ``services/knowledge``, map fixed states to status
codes (``_knowledge_evidence_http``). Every hit carries its resolved citation and where it comes from
(``origin``, ``container``, ``changed_at``; ``services/knowledge/retrieval/hit_origin.py``). A hybrid search also
returns ``timings_ms`` (milliseconds per stage, per Workspace) and logs them as ``knowledge.search.timing``, so a
slow search can be explained. The window route returns a hit's passage with its neighbours for the preview, read
through the same Knowledge scope as the search (``scoped_read``): a key the reader may not see is a 404 like any
unknown key.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import authorize_workspace
from ...services.knowledge.access.bindings import KnowledgeScope, resolve_scope
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.ledger.reading import MAX_READ_WINDOW
from ...services.knowledge.retrieval.evidence import (
    LEXICAL_MODES,
    MAX_RESULT_LIMIT,
    VECTOR_MODES,
    retrieve_workspace_evidence,
)
from ...services.knowledge.retrieval.hit_origin import HitRef, hit_origins
from ...services.knowledge.retrieval.locator import evidence_locator
from ...services.knowledge.retrieval.scoped import scoped_evidence, scoped_read
from ...services.knowledge.retrieval.stage_timing import StageTimer, measuring, timed_stage
from ...services.knowledge.runtime import get_evidence_runtime
from ._knowledge_evidence_http import evidence_http_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])

# A hit without recorded lineage (none found for its source) says so rather than guessing.
_NO_ORIGIN = {"origin": None, "container": None, "changed_at": None}


def _http_error(error: EvidenceLedgerError) -> HTTPException:
    return evidence_http_error(error)


def _hit_ref(workspace_id: str, evidence) -> HitRef:
    return (workspace_id, evidence.source_id or "", evidence.revision_id or "")


def _timings(timer: StageTimer, per_workspace: dict[str, dict[str, int]], scope: KnowledgeScope) -> dict:
    """``{"total": ms, "stages": {stage: ms}, "workspaces": {name: {stage: ms, "total": ms}}}``."""
    stages = timer.as_dict()
    return {
        "total": stages.pop("total", None),
        "stages": stages,
        "workspaces": {scope.name_of(key) or key: values for key, values in per_workspace.items()},
    }


class ProofRequest(BaseModel):
    """Audience proof: untrusted coordinates of a server-owned challenge, nothing else.

    The server's query set runs as the authenticated caller; a caller cannot send queries, hits, results or
    bindings (extra fields are refused). Coordinates other than the challenge id are optional and, when given,
    must equal the challenge's.
    """

    model_config = ConfigDict(extra="forbid")

    challenge_id: str = Field(min_length=8, max_length=64, pattern=r"^[0-9a-f]+$")
    run_id: str | None = Field(default=None, max_length=36)
    pass_key: str | None = Field(default=None, max_length=128)
    publication_card_hash: str | None = Field(default=None, max_length=71)


class EvidenceSearchRequest(BaseModel):
    query_text: str = Field(min_length=1, max_length=2000, description="Terms to search the Workspace evidence for.")
    limit: int | None = Field(default=None, ge=1, le=MAX_RESULT_LIMIT)
    products: list[str] | None = Field(default=None, description="Optional product narrowing.")
    version: str | None = Field(default=None, description="Optional subject version, with products.")
    mode: Literal["hybrid", "lexical", "vector"] = Field(
        default="hybrid",
        description="hybrid fuses lexical and vector (partial answers are marked in mode_states); vector needs "
        "the Instance's embedding space.",
    )
    proof_request: ProofRequest | None = Field(
        default=None,
        description="S1 audience proof: run the server-owned challenge's query set as the caller and record the "
        "result; the request's own query fields are then not used.",
    )


def _search_item(item, *, found_by: list[str], similarity: float | None, relevance: float | None = None) -> dict:
    return {
        "evidence_key": item.evidence_key,
        "text": item.text,
        "citation": item.citation,
        # With ``revision_id`` this addresses the original (``.../revisions/{id}/original``).
        "source_id": item.source_id or None,
        "revision_id": item.revision_id,
        "revision": item.revision_ordinal,
        "span_ordinal": item.span_ordinal,
        "chars": [item.char_start, item.char_end],
        "content_sha256": item.content_sha256,
        "source_title": item.source_title,
        "source_url": item.source_url,
        "products": list(item.products),
        "version": item.version,
        **evidence_locator(item),
        "found_by": found_by,
        "similarity": None if similarity is None else round(similarity, 3),
        "relevance": None if relevance is None else round(relevance, 3),
    }


async def _hybrid_search(db: AsyncSession, runtime, authorized, request: EvidenceSearchRequest) -> dict:
    """Lexical and vector fused over the Workspace and the Workspaces it is bound to read, with stage timings."""
    with measuring() as timer:
        scope = await resolve_scope(db, authorized)
        fused = await scoped_evidence(
            db,
            runtime=runtime,
            scope=scope,
            query_text=request.query_text,
            limit=request.limit,
            products=request.products,
            version=request.version,
        )
        with timed_stage("origin"):
            refs = [_hit_ref(item.workspace_id, item.hit.evidence) for item in fused.evidence]
            origins = await hit_origins(db, refs)
    timings = _timings(timer, fused.workspace_timings, scope)
    logger.info(
        "knowledge.search.timing workspace=%s hits=%d total_ms=%s stages=%s workspaces=%s",
        authorized.project_id, len(fused.evidence), timings["total"], timings["stages"],
        timings["workspaces"],
    )
    return {
        "workspace_id": authorized.project_id,
        "limit": fused.limit,
        "mode_states": dict(fused.workspace_states.get(authorized.project_id, {})),
        "workspace_states": {
            scope.name_of(key) or key: states for key, states in fused.workspace_states.items()
        },
        "evidence": [
            {
                **_search_item(
                    item.hit.evidence,
                    found_by=list(item.hit.modes),
                    similarity=item.hit.similarity,
                    relevance=item.hit.relevance,
                ),
                **origins.get(_hit_ref(item.workspace_id, item.hit.evidence), _NO_ORIGIN),
                "workspace": item.workspace_name,
                "bound": item.workspace_id != authorized.project_id,
            }
            for item in fused.evidence
        ],
        "timings_ms": timings,
    }


@router.post("/search")
async def search_knowledge_evidence(
    workspace_id: str,
    request: EvidenceSearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bounded retrieval; every hit carries a resolved citation. ``hybrid`` fuses lexical and vector over the
    Workspace and the Workspaces it is bound to read; each hit names its Workspace.

    With ``proof_request`` the route records an audience receipt instead: see
    ``services/workflow_runs/documentation/receipt_record.py``."""
    if request.proof_request is not None:
        return await _record_proof(db, current_user, workspace_id, request.proof_request)
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        runtime = get_evidence_runtime()
        if request.mode == "hybrid":
            return await _hybrid_search(db, runtime, authorized, request)
        result = await retrieve_workspace_evidence(
            db,
            runtime=runtime,
            authorized=authorized,
            query_text=request.query_text,
            limit=request.limit,
            modes=VECTOR_MODES if request.mode == "vector" else LEXICAL_MODES,
            products=request.products,
            version=request.version,
        )
        origins = await hit_origins(db, [_hit_ref(result.workspace_id, item) for item in result.evidence])
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return {
        "workspace_id": result.workspace_id,
        "limit": result.limit,
        "mode_states": {request.mode: "ok"},
        "evidence": [
            {
                **_search_item(item, found_by=[request.mode], similarity=item.score),
                **origins.get(_hit_ref(result.workspace_id, item), _NO_ORIGIN),
            }
            for item in result.evidence
        ],
    }


async def _record_proof(db: AsyncSession, current_user: User, workspace_id: str, proof: ProofRequest) -> dict:
    from app.services.workflow_runs.documentation.audience_contract import AudienceProofError

    from ...services.workflow_runs.documentation.receipt_record import record_audience_receipt

    try:
        recorded = await record_audience_receipt(
            db,
            current_user=current_user,
            workspace_id=workspace_id,
            proof_request=proof.model_dump(),
            runtime=get_evidence_runtime(),
        )
    except AudienceProofError as error:
        await db.commit()  # a revoked or expired challenge stays so; nothing else was written
        raise HTTPException(
            status_code=error.status, detail={"code": error.code, "detail": "Audience proof could not be recorded."}
        ) from None
    except EvidenceLedgerError as error:
        await db.rollback()  # the challenge stays open: retry once Knowledge answers
        raise _http_error(error) from None
    from sqlalchemy import select

    from ...models import DocumentationAudienceReceipt

    receipt = (await db.execute(select(DocumentationAudienceReceipt).where(
        DocumentationAudienceReceipt.challenge_id == proof.challenge_id,
        DocumentationAudienceReceipt.expected_principal_id == current_user.id,
    ))).scalar_one()
    await _notify_audience_proof(db, receipt.run_id)
    return {"workspace_id": workspace_id, "proof": recorded}


async def _notify_audience_proof(db: AsyncSession, run_id: str) -> None:
    """The documentation graph consumes the authenticated receipt; standalone tests isolate this integration seam."""
    from ...services.workflow_runs.documentation.s1_graph import audience_receipt_recorded

    await audience_receipt_recorded(db, run_id)


@router.get("/evidence/{evidence_key}/window")
async def read_knowledge_evidence_window(
    workspace_id: str,
    evidence_key: str,
    window: int = Query(default=1, ge=0, le=MAX_READ_WINDOW),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """A hit's passage with up to ``window`` neighbouring passages on each side, for the Search preview."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        scope = await resolve_scope(db, authorized)
        held_by, read = await scoped_read(db, scope=scope, evidence_key=evidence_key, window=window)
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "workspace": scope.name_of(held_by) or held_by,
        "bound": held_by != authorized.project_id,
        "evidence_key": read.evidence_key,
        "citation": read.citation,
        "source_title": read.source_title,
        "source_url": read.source_url,
        "revision": read.revision_ordinal,
        "current": read.current,
        "passages": [
            {"evidence_key": key, "text": text, "is_hit": key == read.evidence_key} for key, text in read.passages
        ],
    }


__all__ = ["router"]
