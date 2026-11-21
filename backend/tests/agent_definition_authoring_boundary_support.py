"""Shared revision and audit row queries and the secret prose marker for the test_agent_definition_authoring_* modules."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentDefinitionRevision, AuditLog
from app.services.agent_definition_authoring import AUDIT_ACTION

SECRET_PROSE = "do-not-leak-this-instruction-text"


async def _revisions(db: AsyncSession, definition_id: str) -> list[AgentDefinitionRevision]:
    return list(
        (
            await db.execute(
                select(AgentDefinitionRevision)
                .where(AgentDefinitionRevision.definition_id == definition_id)
                .order_by(AgentDefinitionRevision.revision_number.asc())
            )
        )
        .scalars()
        .all()
    )


async def _governed_audit_count(db: AsyncSession) -> int:
    """Every governed-write audit row in the database, for "nothing was recorded"."""
    return len(
        (
            await db.execute(select(AuditLog.id).where(AuditLog.action == AUDIT_ACTION))
        )
        .scalars()
        .all()
    )


async def _audit_rows(db: AsyncSession, definition_id: str) -> list[AuditLog]:
    return list(
        (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.action == AUDIT_ACTION,
                    AuditLog.resource_id == definition_id,
                )
                .order_by(AuditLog.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
