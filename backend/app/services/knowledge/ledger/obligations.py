"""Outbox obligations of a revision: owed once, and reopened when a completed one is needed again.

Like the rest of the lifecycle, every function here runs inside the caller's transaction and
never commits.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models.project.knowledge_evidence import (
    OUTBOX_OPERATION_EXTRACT_GRAPH,
    OUTBOX_OPERATION_PROJECT_REVISION,
    OUTBOX_OPERATION_RETIRE_REVISION,
    OUTBOX_STATE_APPLIED,
    OUTBOX_STATE_PENDING,
    KnowledgeProjectionOutboxEntry,
)
from ....time_utils import utc_now

# A completed obligation a new need may reopen. A dead-lettered one is not reopened here:
# its only way back is the audited recovery transition (projection/recovery.py).
_REOPENABLE_OUTBOX_STATES = frozenset({OUTBOX_STATE_APPLIED})


async def _reopen(db: AsyncSession, project_id: str, revision_id: str, operation: str) -> bool:
    """Make one obligation of ``revision_id`` due again from its first span. True when it exists."""
    entry = (
        await db.execute(
            select(KnowledgeProjectionOutboxEntry.id, KnowledgeProjectionOutboxEntry.state).where(
                KnowledgeProjectionOutboxEntry.project_id == project_id,
                KnowledgeProjectionOutboxEntry.revision_id == revision_id,
                KnowledgeProjectionOutboxEntry.operation == operation,
            )
        )
    ).first()
    if entry is None:
        return False
    if entry[1] in _REOPENABLE_OUTBOX_STATES:
        # A pending or claimed obligation is already going to run, and a dead-lettered one
        # belongs to recovery; both are left alone.
        await db.execute(
            update(KnowledgeProjectionOutboxEntry)
            .where(KnowledgeProjectionOutboxEntry.id == entry[0], KnowledgeProjectionOutboxEntry.state == entry[1])
            .values(
                state=OUTBOX_STATE_PENDING,
                attempt_count=0,
                projected_through_ordinal=0,
                next_attempt_at=utc_now(),
                last_failure=None,
                claimed_by=None,
                claimed_at=None,
                claimed_until=None,
                applied_at=None,
            )
        )
    return True


async def _ensure_obligation(db: AsyncSession, project_id: str, revision_id: str, operation: str) -> None:
    """Owe ``operation`` for this revision: a new pending entry, or the completed one reopened."""
    if await _reopen(db, project_id, revision_id, operation):
        return
    db.add(
        KnowledgeProjectionOutboxEntry(
            id=str(uuid.uuid4()),
            project_id=project_id,
            revision_id=revision_id,
            operation=operation,
            state=OUTBOX_STATE_PENDING,
            next_attempt_at=utc_now(),
        )
    )


async def ensure_projection(db: AsyncSession, project_id: str, revision_id: str) -> None:
    """Owe the projection of a revision whose spans were just parsed."""
    await _ensure_obligation(db, project_id, revision_id, OUTBOX_OPERATION_PROJECT_REVISION)


async def ensure_graph_extraction(db: AsyncSession, project_id: str, revision_id: str) -> None:
    """Owe the extraction of a current revision into the Workspace knowledge graph."""
    await _ensure_obligation(db, project_id, revision_id, OUTBOX_OPERATION_EXTRACT_GRAPH)


async def ensure_retirement(db: AsyncSession, project_id: str, revision_id: str) -> None:
    """Owe the removal of this revision's spans from the Workspace database."""
    await _ensure_obligation(db, project_id, revision_id, OUTBOX_OPERATION_RETIRE_REVISION)
