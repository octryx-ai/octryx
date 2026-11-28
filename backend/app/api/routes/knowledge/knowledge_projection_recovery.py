"""Governed projection recovery transport."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.recovery_vocabulary import (
    RECOVERY_OPERATION_REQUEUE,
    RECOVERY_OPERATION_RETRY_NOW,
    RECOVERY_RESULT_NOT_RECOVERABLE,
)

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.projection.recovery import recover_projection
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/projection", tags=["workspace-knowledge"])

# Fixed: it names the boundary without reporting which of the two protected states
# the obligation is in. The response body carries the state itself, which a
# Workspace author can already read from the projection backlog.
_NOT_RECOVERABLE_DETAIL = "This projection obligation cannot be recovered in its current state."


async def _recover(
    db: AsyncSession, *, current_user: User, workspace_id: str, revision_id: str, operation: str
) -> dict:
    try:
        authorized = await authorize_workspace(
            db, current_user=current_user, workspace_id=workspace_id, require_author=True
        )
        recovery = await recover_projection(
            db,
            authorized=authorized,
            revision_id=revision_id,
            operation=operation,
            actor_user_id=current_user.id,
        )
    except WorkspaceWriteForbiddenError:
        raise HTTPException(status_code=403, detail=WORKSPACE_WRITE_FORBIDDEN_DETAIL) from None
    except EvidenceLedgerError as error:
        raise evidence_http_error(error) from None
    if recovery.result == RECOVERY_RESULT_NOT_RECOVERABLE:
        raise HTTPException(status_code=409, detail=_NOT_RECOVERABLE_DETAIL)
    return {
        "workspace_id": authorized.project_id,
        "revision_id": recovery.revision_id,
        "operation": recovery.operation,
        "result": recovery.result,
        "outbox_state": recovery.outbox_state,
        # True only when this request performed the transition, so a repeat is
        # visibly idempotent rather than looking like a second recovery.
        "recovered": recovery.changed,
    }


@router.post("/revisions/{revision_id}/requeue")
async def requeue_dead_lettered_projection(
    workspace_id: str,
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a dead-lettered projection obligation to the queue. A repeat answers ``already_pending`` without a second
    transition."""
    return await _recover(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        revision_id=revision_id,
        operation=RECOVERY_OPERATION_REQUEUE,
    )


@router.post("/revisions/{revision_id}/retry-now")
async def retry_projection_now(
    workspace_id: str,
    revision_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pull a backed-off projection attempt forward so it is due immediately. The attempt count is kept, so this cannot
    widen the retry budget; a dead-lettered obligation must be requeued."""
    return await _recover(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        revision_id=revision_id,
        operation=RECOVERY_OPERATION_RETRY_NOW,
    )
