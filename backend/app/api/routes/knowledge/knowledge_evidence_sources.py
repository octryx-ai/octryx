"""Canonical Workspace Knowledge Evidence transport."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....http_multipart_route import BoundedFormRoute
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import AuthorizedWorkspace, authorize_workspace
from ....services.knowledge.ingestion.media_types import is_sandboxed_media_type
from ....services.knowledge.ingestion.sandboxed_ingest import ingest_sandboxed_source
from ....services.knowledge.ingestion.text_ingest import MAX_UPLOAD_BYTES, ingest_text_source
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.ledger.lifecycle import remove_source
from ....services.knowledge.ledger.queries import (
    MAX_SOURCE_LIMIT,
    get_source_detail,
    projection_backlog,
    workspace_products,
)
from ....services.knowledge.ledger.source_page import list_source_page
from ....services.knowledge.runtime import get_evidence_runtime
from ....services.knowledge.sources.sync.source_origins import source_origins
from ._knowledge_evidence_sources_http import _BYTE_LIMIT_DETAIL, _http_error, authorize_author
from .knowledge_evidence_projection import router as projection_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"],
                   route_class=BoundedFormRoute)


def _revision_answer(authorized: AuthorizedWorkspace, ingested, *, sandboxed: bool) -> dict:
    return {
        "workspace_id": authorized.project_id,
        "source_id": ingested.source_id,
        "source_key": ingested.source_key,
        "revision_id": ingested.revision_id,
        "revision_ordinal": ingested.revision_ordinal,
        "content_sha256": ingested.content_sha256,
        "media_type": ingested.media_type,
        "byte_size": ingested.byte_size,
        "span_count": ingested.span_count,
        "created": ingested.created,
        "projection": "parsing" if sandboxed and not ingested.span_count else "pending",
    }


@router.post("/sources", status_code=201)
async def create_knowledge_source_revision(
    workspace_id: str,
    source_key: str = Form(..., description="Stable, Workspace-scoped document key."),
    display_title: str = Form(..., description="Human-facing title of the document."),
    file: UploadFile = File(
        ...,
        description="Text-native document (txt, md, html, csv, json, xml), or PDF/Office (pdf, docx, pptx, xlsx) "
        "for the Docling sandbox.",
    ),
    source_url: str | None = Form(
        None, description="Optional http(s) link to exactly where this revision came from (e.g. a Confluence page)."
    ),
    products: str | None = Form(
        None, description="Optional comma-separated product keys this revision is about (e.g. spring-boot)."
    ),
    version: str | None = Form(None, description="Optional subject version, e.g. 4.0 (requires products)."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ingest one document as an immutable Workspace revision."""
    authorized = await authorize_author(db, current_user, workspace_id)

    # Bounded before anything else looks at the bytes; the declared content type is
    # policy input only and the client-supplied file name is never read.
    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=_BYTE_LIMIT_DETAIL)

    sandboxed = is_sandboxed_media_type(file.content_type)
    ingest = ingest_sandboxed_source if sandboxed else ingest_text_source
    try:
        runtime = get_evidence_runtime()
        ingested = await ingest(
            db,
            runtime=runtime,
            authorized=authorized,
            source_key=source_key,
            display_title=display_title,
            declared_media_type=file.content_type,
            data=payload,
            created_by=current_user.id,
            source_url=source_url,
            products=products,
            version=version,
        )
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return _revision_answer(authorized, ingested, sandboxed=sandboxed)


@router.get("/sources")
async def list_knowledge_sources(
    workspace_id: str,
    limit: int | None = Query(
        default=None,
        ge=1,
        le=MAX_SOURCE_LIMIT,
        description=f"Maximum sources to return (1-{MAX_SOURCE_LIMIT}); omitted uses the service default.",
    ),
    cursor: str | None = Query(default=None, max_length=256, description="Opaque cursor of the next page."),
    query: str | None = Query(default=None, max_length=200, description="Case-insensitive title or key filter."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List this Workspace's sources with their revision counts. The page bound is declared here for the OpenAPI
    contract and re-checked by ``list_source_page`` for non-HTTP callers."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        summaries, next_cursor = await list_source_page(db, authorized, limit=limit, cursor=cursor, query=query)
        backlog = await projection_backlog(db, authorized)
        origins = await source_origins(db, authorized.project_id, [(s.source_id, s.source_key) for s in summaries])
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "sources": [
            {
                "source_id": item.source_id,
                "source_key": item.source_key,
                "display_title": item.display_title,
                "revision_count": item.revision_count,
                "latest_revision_ordinal": item.latest_revision_ordinal,
                "origin": origins[item.source_id],  # from stored lineage
            }
            for item in summaries
        ],
        "projection_backlog": backlog.by_state,
        # Additive: null when this is the last page.
        "next_cursor": next_cursor,
    }


@router.get("/products")
async def list_knowledge_products(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The products (and their versions) this Workspace's current Knowledge is about."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        products = await workspace_products(db, authorized)
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return {"workspace_id": authorized.project_id, "products": products}


@router.get("/sources/{source_id}")
async def get_knowledge_source(
    workspace_id: str,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One source of this Workspace with its immutable revisions."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        detail = await get_source_detail(db, authorized, source_id)
        source = detail.source
        origin = await source_origins(db, authorized.project_id, [(source.source_id, source.source_key)])
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    # The revisions' originals, views and diffs are served by ``knowledge_source_originals``.
    return {
        "workspace_id": authorized.project_id,
        "source_id": detail.source.source_id,
        "source_key": detail.source.source_key,
        "display_title": detail.source.display_title,
        "origin": origin[detail.source.source_id],  # from stored lineage
        "revisions": [
            {
                "revision_id": revision.revision_id,
                "revision_ordinal": revision.revision_ordinal,
                "content_sha256": revision.content_sha256,
                "media_type": revision.media_type,
                "byte_size": revision.byte_size,
                "span_count": revision.span_count,
                "state": revision.state,
            }
            for revision in detail.revisions
        ],
    }


@router.delete("/sources/{source_id}")
async def remove_knowledge_source(
    workspace_id: str,
    source_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tombstone one source: it leaves the served Knowledge, while the ledger keeps its history."""
    authorized = await authorize_author(db, current_user, workspace_id)
    try:
        tombstoned = await remove_source(db, authorized=authorized, source_id=source_id, actor_id=current_user.id)
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    return {
        "workspace_id": authorized.project_id,
        "source_id": source_id,
        "tombstoned_revisions": tombstoned,
        "projection": "retiring",
    }


# Included after the routes above so the registration order stays the same.
router.include_router(projection_router)
