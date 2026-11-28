"""Retention of observability data."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, cast, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ConnectorHealthLog, DeviceJobEvent, TurnTrace

OBSERVABILITY_RETENTION_ENTITIES = {"turn_trace_content", "connector_health_log", "device_job_events"}
CONTENT_REMOVED = {"retention": "content removed"}
BATCH = 1000


async def apply_observability_retention(db: AsyncSession, *, entity_type: str, cutoff: datetime) -> int | None:
    if entity_type == "turn_trace_content":
        ids = (await db.execute(select(TurnTrace.id).where(
            TurnTrace.created_at < cutoff,
            # json has no equality operator on PostgreSQL: compare the stored text instead.
            cast(TurnTrace.input_messages_json, String) != "[]").limit(BATCH))).scalars().all()
        if ids:
            await db.execute(update(TurnTrace).where(TurnTrace.id.in_(ids)).values(
                input_messages_json=[], tool_trace_json=[], context_snapshot_json=CONTENT_REMOVED,
                raw_output=CONTENT_REMOVED))
        return len(ids)
    if entity_type == "connector_health_log":
        result = await db.execute(delete(ConnectorHealthLog).where(ConnectorHealthLog.checked_at < cutoff))
        return int(result.rowcount or 0)
    if entity_type == "device_job_events":
        result = await db.execute(delete(DeviceJobEvent).where(DeviceJobEvent.created_at < cutoff))
        return int(result.rowcount or 0)
    return None


__all__ = ["OBSERVABILITY_RETENTION_ENTITIES", "apply_observability_retention"]
