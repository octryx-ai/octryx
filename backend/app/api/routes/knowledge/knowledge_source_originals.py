"""Originals of Workspace Knowledge revisions: bytes, display view, and revision diff."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import authorize_workspace
from ....services.knowledge.display.original_view import read_original_view
from ....services.knowledge.display.revision_diff import diff_revisions
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.ledger.original import MAX_ID_CHARS, original_headers, read_original
from ....services.knowledge.runtime import get_evidence_runtime
from ._knowledge_original_http import original_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge", tags=["workspace-knowledge"])

# The view is JSON a page renders, but its strings came from an untrusted document: never cached.
_VIEW_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


@router.get("/sources/{source_id}/revisions/{revision_id}/original")
async def get_knowledge_source_original(
    workspace_id: str,
    source_id: str,
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Digest-verified original bytes of one revision (PDF inline, else a download)."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        original = await read_original(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            source_id=source_id,
            revision_id=revision_id,
        )
    except EvidenceLedgerError as error:
        raise original_http_error(error) from None
    return Response(content=original.data, media_type=original.media_type, headers=original_headers(original))


@router.get("/sources/{source_id}/revisions/{revision_id}/view")
async def get_knowledge_source_original_view(
    workspace_id: str,
    source_id: str,
    revision_id: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One revision's original for inline display: sanitized ``html`` (HTML originals) and ``text``."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        view = await read_original_view(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            source_id=source_id,
            revision_id=revision_id,
        )
    except EvidenceLedgerError as error:
        raise original_http_error(error) from None
    response.headers.update(_VIEW_HEADERS)
    return view


@router.get("/sources/{source_id}/diff")
async def get_knowledge_source_revision_diff(
    workspace_id: str,
    source_id: str,
    response: Response,
    from_revision_id: str = Query(..., min_length=1, max_length=MAX_ID_CHARS, description="Older side."),
    to_revision_id: str = Query(..., min_length=1, max_length=MAX_ID_CHARS, description="Newer side."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Bounded unified line diff of two revisions of this source (``state``: ok, identical, too_large)."""
    try:
        authorized = await authorize_workspace(db, current_user=current_user, workspace_id=workspace_id)
        diff = await diff_revisions(
            db,
            runtime=get_evidence_runtime(),
            authorized=authorized,
            source_id=source_id,
            from_revision_id=from_revision_id,
            to_revision_id=to_revision_id,
        )
    except EvidenceLedgerError as error:
        raise original_http_error(error) from None
    response.headers.update(_VIEW_HEADERS)
    return diff
