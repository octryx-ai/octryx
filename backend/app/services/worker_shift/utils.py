from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import (
    AgentWorker,
    User,
    WorkerDailyAgenda,
    WorkerMonitorEvent,
    WorkerShift,
    WorkerTrustEvent,
)
from ...time_utils import ensure_utc, utc_now_aware
from ..admin.governance.admin_access_service import is_global_admin


def _safe_timezone(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(str(value or "UTC"))
    except Exception:
        return ZoneInfo("UTC")


def _local_now(worker: AgentWorker, now: datetime | None = None) -> datetime:
    current = ensure_utc(now) or utc_now_aware()
    return current.astimezone(_safe_timezone(worker.timezone))


def _local_date(worker: AgentWorker, current: datetime | None = None) -> date:
    return _local_now(worker, current).date()


def _serialize_shift(row: WorkerShift) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "shift_start": row.shift_start.isoformat() if row.shift_start else None,
        "shift_end": row.shift_end.isoformat() if row.shift_end else None,
        "shift_type": row.shift_type,
        "handover_summary": row.handover_summary,
        "open_items": list(row.open_items or []),
        "completed_items": list(row.completed_items or []),
        "escalations_count": int(row.escalations_count or 0),
        "autonomous_actions_count": int(row.autonomous_actions_count or 0),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize_agenda(row: WorkerDailyAgenda) -> dict[str, Any]:
    return {
        "id": row.id,
        "worker_id": row.worker_id,
        "date": row.date.isoformat(),
        "agenda_items": list(row.agenda_items or []),
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "status": row.status,
    }


async def _require_admin(db: AsyncSession, current_user: User) -> None:
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")


async def _get_worker(db: AsyncSession, worker_id: str) -> AgentWorker:
    worker = (
        await db.execute(
            select(AgentWorker)
            .options(
                selectinload(AgentWorker.runtime_state),
                selectinload(AgentWorker.onboarding),
                selectinload(AgentWorker.monitors),
            )
            .where(AgentWorker.id == worker_id)
        )
    ).scalar_one_or_none()
    if worker is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    return worker


def _is_within_work_hours(worker: AgentWorker) -> bool:
    if worker.schedule_type == "always_on":
        return True
    now_local = _local_now(worker)
    if worker.schedule_type == "on_call":
        schedule = dict(worker.on_call_schedule or {})
        if schedule.get("enabled") is False:
            return False
        return bool(schedule.get("active", True))
    start = worker.work_hours_start
    end = worker.work_hours_end
    if start is None or end is None:
        return True
    current_time = now_local.time().replace(tzinfo=None)
    if start <= end:
        return start <= current_time <= end
    return current_time >= start or current_time <= end


def _default_shift_type(worker: AgentWorker) -> str:
    if worker.schedule_type == "on_call":
        return "on_call"
    hour = _local_now(worker).hour
    if 6 <= hour < 14:
        return "morning"
    if 14 <= hour < 22:
        return "evening"
    return "night"


async def _latest_shift(db: AsyncSession, worker_id: str) -> WorkerShift | None:
    return (
        await db.execute(
            select(WorkerShift)
            .where(WorkerShift.worker_id == worker_id)
            .order_by(WorkerShift.shift_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _active_shift(db: AsyncSession, worker_id: str) -> WorkerShift | None:
    return (
        await db.execute(
            select(WorkerShift)
            .where(WorkerShift.worker_id == worker_id, WorkerShift.status == "active")
            .order_by(WorkerShift.shift_start.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _collect_open_items(
    db: AsyncSession,
    worker: AgentWorker,
    shift_start: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(WorkerMonitorEvent)
                .where(WorkerMonitorEvent.worker_id == worker.id, WorkerMonitorEvent.resolved_at.is_(None))
                .order_by(WorkerMonitorEvent.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    items = [
        {
            "type": "monitor_alert",
            "priority": 1 if row.severity == "critical" else 2,
            "title": f"{row.severity.upper()} monitor event",
            "description": f"Detected value {row.detected_value or 'n/a'} via {row.triggered_action or 'log'}",
            "monitor_event_id": row.id,
        }
        for row in rows
    ]
    runtime = worker.runtime_state
    if runtime and runtime.current_session_id:
        items.append(
            {
                "type": "active_session",
                "priority": 1,
                "title": "Active worker session",
                "description": f"Current session {runtime.current_session_id} still attached to worker runtime.",
                "session_id": runtime.current_session_id,
            }
        )
    previous_shift = await _latest_shift(db, worker.id)
    if previous_shift and previous_shift.id != getattr(shift_start, "id", None):
        for item in previous_shift.open_items or []:
            items.append({**dict(item), "priority": int(dict(item).get("priority") or 2)})
    items.sort(key=lambda item: (int(item.get("priority") or 99), str(item.get("title") or "")))
    return items[:12]


async def _collect_completed_items(
    db: AsyncSession,
    worker: AgentWorker,
    shift_start: datetime,
) -> list[dict[str, Any]]:
    resolved_rows = (
        (
            await db.execute(
                select(WorkerMonitorEvent)
                .where(
                    WorkerMonitorEvent.worker_id == worker.id,
                    WorkerMonitorEvent.created_at >= shift_start,
                    WorkerMonitorEvent.resolved_at.is_not(None),
                )
                .order_by(WorkerMonitorEvent.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    trust_rows = (
        (
            await db.execute(
                select(WorkerTrustEvent)
                .where(
                    WorkerTrustEvent.worker_id == worker.id,
                    WorkerTrustEvent.created_at >= shift_start,
                    WorkerTrustEvent.event_type.in_(("success", "human_approved")),
                )
                .order_by(WorkerTrustEvent.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    items: list[dict[str, Any]] = []
    for row in resolved_rows:
        items.append(
            {
                "type": "resolved_monitor",
                "title": f"Resolved {row.severity} monitor event",
                "description": row.resolution_summary or "Recovered during shift.",
                "monitor_event_id": row.id,
            }
        )
    for row in trust_rows:
        items.append(
            {
                "type": "trust_success",
                "title": f"Trust event: {row.event_type}",
                "description": row.reason or "Worker completed a successful action.",
                "trust_event_id": row.id,
            }
        )
    return items[:12]


async def _build_handover_summary(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    shift: WorkerShift,
    open_items: list[dict[str, Any]],
    completed_items: list[dict[str, Any]],
) -> str:
    next_focus = open_items[0]["title"] if open_items else "No urgent open items."
    return (
        f"Shift handover for {worker.name}: "
        f"{len(completed_items)} items completed, {len(open_items)} open items remain. "
        f"Next focus: {next_focus}"
    )
