"""Workspace Knowledge upkeep triggers: the backfill of the runs' documents and one manual projection batch."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.outbox_lease import MAX_CLAIMED_BY_CHARS

from ....db import get_db
from ....models import User
from ....services.auth import get_current_user
from ....services.knowledge.ledger.errors import EvidenceLedgerError
from ....services.knowledge.projection.projector import EvidenceProjector
from ....services.knowledge.runtime import get_evidence_runtime
from ._knowledge_evidence_sources_http import _http_error, authorize_author

router = APIRouter()


_PROJECTION_WORKER_PREFIX = "api"


def _projection_worker_id(user_id: object) -> str:
    return f"{_PROJECTION_WORKER_PREFIX}:{user_id}"[:MAX_CLAIMED_BY_CHARS]  # truncated, not hashed: auditable


@router.post("/projection/run")
async def run_workspace_projection(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply one bounded batch of one due projection obligation of this Workspace."""
    authorized = await authorize_author(db, current_user, workspace_id)
    try:
        projector = EvidenceProjector(get_evidence_runtime())
        outcome = await projector.project_once(
            db, worker_id=_projection_worker_id(current_user.id), project_id=authorized.project_id
        )
    except EvidenceLedgerError as error:
        raise _http_error(error) from None
    if outcome is None:
        return {"workspace_id": authorized.project_id, "claimed": False}
    return {
        "workspace_id": authorized.project_id,
        "claimed": True,
        "revision_id": outcome.revision_id,
        "applied": outcome.applied,
        "spans_projected": outcome.spans_projected,
        # True means this revision is not finished: call again to continue.
        "more_spans_pending": outcome.more_spans_pending,
        "failure": outcome.failure,
        "outbox_state": outcome.outbox_state,
    }
