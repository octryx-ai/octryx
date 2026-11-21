"""Governed projection recovery transport.

Thin by design: authenticate, authorize the Workspace as an author, delegate to
``services/knowledge_evidence/projection_recovery``, and map its fixed decision
tokens onto status codes. No policy, no query, no state rule lives here.

Two explicit endpoints rather than one endpoint with an operation field, so the
operation is part of the served route table instead of a switch inside a request
body. The third operation token exists only for the identical-upload path inside the
ledger and is deliberately unreachable from HTTP.

Scope comes from the path and refusals are indistinguishable: an unknown Workspace, a
Workspace the caller has no role in, a malformed Workspace id, and a revision that is
unknown or belongs to another Workspace all render the same fixed 404 body. A 403
appears only for a caller who can already read the Workspace but is not one of its
authors. A 409 means the obligation exists and is visible but its current state does
not permit the operation — which is the ``claimed``/``applied`` boundary, not an
error.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.recovery_vocabulary import (
    RECOVERY_OPERATION_REQUEUE,
    RECOVERY_OPERATION_RETRY_NOW,
    RECOVERY_RESULT_NOT_RECOVERABLE,
)

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.access.authorization import (
    WORKSPACE_WRITE_FORBIDDEN_DETAIL,
    WorkspaceWriteForbiddenError,
    authorize_workspace,
)
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.projection.recovery import recover_projection
from ._knowledge_evidence_http import evidence_http_error

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/knowledge/projection", tags=["workspace-knowledge"])

# Fixed: it names the boundary without reporting which of the two protected states
# the obligation is in. The response body carries the state itself, which a
# Workspace author can already read from the projection backlog.
_NOT_RECOVERABLE_DETAIL = "This projection obligation cannot be recovered in its current state."


async def _recover(
    db: AsyncSession, *, current_user: User, workspace_id: str, revision_id: str, operation: str
) -> dict:
    """The one authorize-delegate-render path both endpoints share."""
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
    """Return a dead-lettered projection obligation to the queue.

    The attempt budget is reset and the obligation becomes due immediately; the
    immutable revision and the projection cursor are untouched, so the next run
    continues from the spans that were already projected. Repeating the call answers
    ``already_pending`` without a second transition.
    """
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
    """Pull a backed-off projection attempt forward so it is due immediately.

    Only an obligation that is already queued for a later attempt is eligible: the
    attempt count is preserved, so this cannot widen the bounded retry budget, and a
    dead-lettered obligation must be requeued explicitly instead.
    """
    return await _recover(
        db,
        current_user=current_user,
        workspace_id=workspace_id,
        revision_id=revision_id,
        operation=RECOVERY_OPERATION_RETRY_NOW,
    )
