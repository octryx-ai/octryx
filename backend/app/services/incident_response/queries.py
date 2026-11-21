"""Read side of incident response: paused entities and the kill switch audit log."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.incident_response import KillSwitchLog, PausedEntity


async def list_paused_entities(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    incident_id: str | None = None,
    include_resumed: bool = False,
) -> list[dict[str, Any]]:
    """List paused entities with optional filters."""
    stmt = select(PausedEntity)
    if project_id:
        stmt = stmt.where(PausedEntity.project_id == project_id)
    if incident_id:
        stmt = stmt.where(PausedEntity.incident_id == incident_id)
    if not include_resumed:
        stmt = stmt.where(PausedEntity.resumed_at.is_(None))
    stmt = stmt.order_by(PausedEntity.paused_at.desc())

    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": p.id,
            "entity_type": p.entity_type,
            "entity_id": p.entity_id,
            "project_id": p.project_id,
            "reason": p.reason,
            "incident_id": p.incident_id,
            "paused_at": p.paused_at.isoformat() if p.paused_at else None,
            "resumed_at": p.resumed_at.isoformat() if p.resumed_at else None,
        }
        for p in rows
    ]


async def list_kill_switch_logs(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    target_type: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List kill switch audit logs."""
    stmt = select(KillSwitchLog)
    if project_id:
        stmt = stmt.where(KillSwitchLog.project_id == project_id)
    if target_type:
        stmt = stmt.where(KillSwitchLog.target_type == target_type)
    stmt = stmt.order_by(KillSwitchLog.created_at.desc()).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": log.id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "project_id": log.project_id,
            "user_id": log.user_id,
            "reason": log.reason,
            "incident_id": log.incident_id,
            "details": log.details,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in rows
    ]
