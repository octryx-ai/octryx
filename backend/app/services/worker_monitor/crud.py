from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.worker_monitor.common import (
    _get_monitor,
    _get_worker,
    _normalize_action,
    _normalize_monitor_type,
    _normalize_string,
    _require_admin,
    serialize_worker_monitor,
    serialize_worker_monitor_event,
)

from ...models import User, WorkerMonitor, WorkerMonitorEvent


async def list_worker_monitors(db: AsyncSession, *, worker_id: str, current_user: User) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    rows = (
        (
            await db.execute(
                select(WorkerMonitor)
                .where(WorkerMonitor.worker_id == worker_id)
                .order_by(WorkerMonitor.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_worker_monitor(row) for row in rows]


async def create_worker_monitor(
    db: AsyncSession, *, worker_id: str, current_user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    row = WorkerMonitor(
        id=str(uuid.uuid4()),
        worker_id=worker_id,
        name=str(payload.get("name") or "").strip(),
        monitor_type=_normalize_monitor_type(payload.get("monitor_type")),
        check_interval_minutes=max(1, int(payload.get("check_interval_minutes") or 15)),
        check_query=_normalize_string(payload.get("check_query")),
        threshold_config=dict(payload.get("threshold_config") or {}),
        action_on_warning=_normalize_action(payload.get("action_on_warning")),
        action_on_critical=_normalize_action(payload.get("action_on_critical")),
        baseline_json=dict(payload.get("baseline_json") or {}),
        is_active=bool(payload.get("is_active", True)),
    )
    if not row.name:
        raise HTTPException(status_code=422, detail="name is required")
    db.add(row)
    await db.commit()
    return serialize_worker_monitor(row)


async def patch_worker_monitor(
    db: AsyncSession,
    *,
    worker_id: str,
    monitor_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    row = await _get_monitor(db, worker_id, monitor_id)
    if "name" in payload and payload.get("name") is not None:
        row.name = str(payload["name"]).strip()
    if "monitor_type" in payload and payload.get("monitor_type") is not None:
        row.monitor_type = _normalize_monitor_type(payload.get("monitor_type"))
    if "check_interval_minutes" in payload and payload.get("check_interval_minutes") is not None:
        row.check_interval_minutes = max(1, int(payload["check_interval_minutes"]))
    if "check_query" in payload:
        row.check_query = _normalize_string(payload.get("check_query"))
    if "threshold_config" in payload and payload.get("threshold_config") is not None:
        row.threshold_config = dict(payload["threshold_config"])
    if "action_on_warning" in payload:
        row.action_on_warning = _normalize_action(payload.get("action_on_warning"))
    if "action_on_critical" in payload:
        row.action_on_critical = _normalize_action(payload.get("action_on_critical"))
    if "baseline_json" in payload and payload.get("baseline_json") is not None:
        row.baseline_json = dict(payload["baseline_json"])
    if "is_active" in payload and payload.get("is_active") is not None:
        row.is_active = bool(payload["is_active"])
    await db.commit()
    return serialize_worker_monitor(row)


async def list_worker_monitor_events(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    limit: int = 50,
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    rows = (
        (
            await db.execute(
                select(WorkerMonitorEvent)
                .where(WorkerMonitorEvent.worker_id == worker_id)
                .order_by(WorkerMonitorEvent.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        )
        .scalars()
        .all()
    )
    return [serialize_worker_monitor_event(row) for row in rows]
