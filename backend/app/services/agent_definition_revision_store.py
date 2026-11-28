"""Revision reads, revision inserts and their stored-state constants. Nothing here writes the live Agent Definition
aggregate."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.integrity_errors import violates_unique_constraint
from ..models import AgentDefinitionRevision, AgentStep
from ..models.agent.agent_definition_revision import REVISION_STATUS_PUBLISHED

ALREADY_PUBLISHED_DETAIL = "Revision is already published"
NOT_PUBLISHED_DETAIL = "Only a published revision can be restored"

#: The one unique constraint whose violation is a concurrency conflict here.
UNIQUE_REVISION_NUMBER_CONSTRAINT = "uq_agent_definition_revision_number"

#: 409. Retryable: another request took the revision number first.
REVISION_NUMBER_CONFLICT_DETAIL = (
    "A concurrent revision was created for this definition; retry the request."
)

#: 422. Not retryable as-is: some other stored reference of the aggregate no
#: longer satisfies the schema, so a blind retry would fail the same way. Kept
#: distinct from the 409 so a client cannot read a broken reference as a race.
#: Carries no database, driver, or constraint detail.
REVISION_STORAGE_INTEGRITY_DETAIL = (
    "The revision could not be stored because the definition's stored references "
    "are no longer consistent; reload the definition before retrying."
)


async def load_definition_steps(
    db: AsyncSession, definition_id: str
) -> list[AgentStep]:
    # An explicit query: the lazy ``AgentDefinition.steps`` raises ``MissingGreenlet`` in async code.
    result = await db.execute(
        select(AgentStep)
        .where(AgentStep.agent_id == definition_id)
        .order_by(AgentStep.position.asc(), AgentStep.created_at.asc())
    )
    return list(result.scalars().all())


async def list_agent_definition_revisions(
    db: AsyncSession, definition_id: str
) -> list[AgentDefinitionRevision]:
    result = await db.execute(
        select(AgentDefinitionRevision)
        .where(AgentDefinitionRevision.definition_id == definition_id)
        .order_by(AgentDefinitionRevision.revision_number.desc())
    )
    return list(result.scalars().all())


async def get_published_revision(
    db: AsyncSession, definition_id: str
) -> AgentDefinitionRevision | None:
    result = await db.execute(
        select(AgentDefinitionRevision)
        .where(
            AgentDefinitionRevision.definition_id == definition_id,
            AgentDefinitionRevision.status == REVISION_STATUS_PUBLISHED,
        )
        .order_by(AgentDefinitionRevision.revision_number.desc())
        .limit(1)
    )
    return result.scalars().first()


async def insert_revision(db: AsyncSession, revision: AgentDefinitionRevision) -> None:
    # Only a ``uq_agent_definition_revision_number`` collision is a retryable 409 (other failures are 422). Nothing
    # retries in place: ``get_db`` rolls the request back before any client retry, so a failed restore changes nothing.
    db.add(revision)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise _integrity_state(exc) from exc


def _integrity_state(exc: IntegrityError) -> HTTPException:
    if violates_unique_constraint(
        exc,
        constraint_name=UNIQUE_REVISION_NUMBER_CONSTRAINT,
        table=AgentDefinitionRevision.__tablename__,
        columns=("definition_id", "revision_number"),
    ):
        return HTTPException(status_code=409, detail=REVISION_NUMBER_CONFLICT_DETAIL)
    return HTTPException(status_code=422, detail=REVISION_STORAGE_INTEGRITY_DETAIL)


def serialize_revision(revision: AgentDefinitionRevision) -> dict[str, Any]:
    return {
        "id": revision.id,
        "definition_id": revision.definition_id,
        "revision_number": int(revision.revision_number),
        "status": revision.status,
        "checksum": revision.checksum,
        "snapshot": revision.snapshot,
        "validation": revision.validation,
        "restored_from_revision_id": revision.restored_from_revision_id,
        "created_by": revision.created_by,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "published_by": revision.published_by,
        "published_at": (
            revision.published_at.isoformat() if revision.published_at else None
        ),
        "approved_by": revision.approved_by,
        "approved_at": revision.approved_at.isoformat() if revision.approved_at else None,
    }
