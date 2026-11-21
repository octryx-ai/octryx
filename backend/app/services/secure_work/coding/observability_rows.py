"""The rows a coding observability view reads: usage, tool calls, turn traces and audit records."""

from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, ToolCall, TurnTrace, UsageEvent, WorkCodingAuditEvent


async def _usage_events(db: AsyncSession, session_ids: list[str]) -> list[UsageEvent]:
    if not session_ids:
        return []
    return list(
        (
            await db.execute(
                select(UsageEvent)
                .where(UsageEvent.session_id.in_(session_ids))
                .order_by(UsageEvent.created_at.asc(), UsageEvent.id.asc())
            )
        ).scalars()
    )


async def _tool_calls(db: AsyncSession, session_ids: list[str]) -> list[ToolCall]:
    if not session_ids:
        return []
    return list(
        (
            await db.execute(
                select(ToolCall)
                .where(ToolCall.session_id.in_(session_ids))
                .order_by(ToolCall.created_at.asc(), ToolCall.id.asc())
            )
        ).scalars()
    )


async def _turn_traces(db: AsyncSession, session_ids: list[str]) -> list[TurnTrace]:
    if not session_ids:
        return []
    return list(
        (
            await db.execute(
                select(TurnTrace)
                .where(TurnTrace.session_id.in_(session_ids))
                .order_by(TurnTrace.created_at.asc(), TurnTrace.id.asc())
            )
        ).scalars()
    )


async def _coding_events(db: AsyncSession, work_item_id: str) -> list[WorkCodingAuditEvent]:
    return list(
        (
            await db.execute(
                select(WorkCodingAuditEvent)
                .where(WorkCodingAuditEvent.work_item_id == work_item_id)
                .order_by(WorkCodingAuditEvent.created_at.asc(), WorkCodingAuditEvent.id.asc())
            )
        ).scalars()
    )


async def _audit_logs(db: AsyncSession, work_item_id: str, session_ids: list[str]) -> list[AuditLog]:
    clauses = [and_(AuditLog.resource_type == "work_item", AuditLog.resource_id == work_item_id)]
    if session_ids:
        clauses.append(AuditLog.session_id.in_(session_ids))
    return list(
        (
            await db.execute(
                select(AuditLog).where(or_(*clauses)).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            )
        ).scalars()
    )
