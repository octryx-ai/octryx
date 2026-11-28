"""The Workspace's answer feedback: what people liked and disliked about the agent's answers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    AuthorizedWorkspace,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.memory.errors import MemoryRefusedError
from ....services.knowledge.memory.feedback_query import (
    DEFAULT_LISTED,
    FeedbackFilter,
    list_feedback,
    parse_feedback_filter,
    summarize_feedback,
)
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/feedback", tags=["workspace-knowledge"])


async def _authorized_reviewer(db: AsyncSession, user: User, workspace_id: str) -> AuthorizedWorkspace:
    try:
        authorized = await authorize_workspace(db, current_user=user, workspace_id=workspace_id)
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    if not authorized.may_author:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL)
    return authorized


def _filter(rating: str | None, aspect: str | None, workflow_key: str | None, limit: int) -> FeedbackFilter:
    try:
        return parse_feedback_filter(rating=rating, aspect=aspect, workflow_key=workflow_key, limit=limit)
    except MemoryRefusedError as error:
        raise HTTPException(status_code=422, detail=error.message) from None


@router.get("")
async def list_workspace_feedback(
    workspace_id: str,
    rating: str | None = None,
    aspect: str | None = None,
    workflow_key: str | None = None,
    limit: int = DEFAULT_LISTED,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Feedback of this Workspace, newest first; filters: rating, aspect, workflow_key."""
    authorized = await _authorized_reviewer(db, current_user, workspace_id)
    where = _filter(rating, aspect, workflow_key, limit)
    return {
        "workspace_id": authorized.project_id,
        "items": await list_feedback(db, authorized=authorized, where=where),
    }


@router.get("/summary")
async def summarize_workspace_feedback(
    workspace_id: str,
    rating: str | None = None,
    aspect: str | None = None,
    workflow_key: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Good/bad per workflow and liked/disliked per aspect, over the same filters as the list."""
    authorized = await _authorized_reviewer(db, current_user, workspace_id)
    return await summarize_feedback(db, authorized=authorized, where=_filter(rating, aspect, workflow_key, 1))
