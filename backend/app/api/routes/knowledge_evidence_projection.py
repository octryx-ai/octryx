"""Workspace Knowledge upkeep triggers: the backfill of the runs' documents and one manual projection batch.

Included into the ``/api/v1/workspaces/{workspace_id}/knowledge`` router by ``knowledge_evidence_sources.py``;
this router has no prefix of its own.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.knowledge.projection.outbox_lease import MAX_CLAIMED_BY_CHARS

from ...db import get_db
from ...models import User
from ...services.auth import get_current_user
from ...services.knowledge.ledger.errors import EvidenceLedgerError
from ...services.knowledge.projection.projector import EvidenceProjector
from ...services.knowledge.runtime import get_evidence_runtime
from ._knowledge_evidence_sources_http import _http_error, authorize_author

router = APIRouter()


_PROJECTION_WORKER_PREFIX = "api"


def _projection_worker_id(user_id: object) -> str:
    """Lease identity of one authorized manual run, bounded to the column width.

    Carries who triggered the drain, so a lease in the outbox is attributable; the
    64-character bound is the ``claimed_by`` column, and the identifier is truncated
    rather than hashed so it stays readable in an audit.
    """
    return f"{_PROJECTION_WORKER_PREFIX}:{user_id}"[:MAX_CLAIMED_BY_CHARS]


@router.post("/projection/run")
async def run_workspace_projection(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply one bounded batch of one due projection obligation of this Workspace.

    Explicit rather than fire-and-forget: the committed outbox entry is the
    handoff, and this endpoint is the authorized trigger that drains it while the
    feature has no background worker of its own.

    Bounded twice over: one call claims at most one entry and projects at most
    ``projector.MAX_SPANS_PER_RUN`` spans of it. A revision with more spans answers
    ``applied: false`` with ``more_spans_pending: true`` and stays pending, so no
    single request can turn into thousands of sequential dependency calls. Draining a
    large revision therefore needs repeated calls until ``claimed`` is false — which
    is exactly why the background projector is the activation gate for enabling this
    feature in a shared environment.
    """
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
