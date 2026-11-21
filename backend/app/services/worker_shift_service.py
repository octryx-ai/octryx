from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.services.worker_shift.utils import (
    _active_shift,
    _build_handover_summary,
    _collect_completed_items,
    _collect_open_items,
    _default_shift_type,
    _get_worker,
    _is_within_work_hours,
    _latest_shift,
    _local_date,
    _require_admin,
    _serialize_agenda,
    _serialize_shift,
)

from ..models import AgentWorker, User, WorkerDailyAgenda, WorkerShift
from ..time_utils import utc_now

logger = logging.getLogger(__name__)


async def list_worker_shifts(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    limit: int = 20,
) -> list[dict[str, Any]]:
    await _require_admin(db, current_user)
    await _get_worker(db, worker_id)
    rows = (
        (
            await db.execute(
                select(WorkerShift)
                .where(WorkerShift.worker_id == worker_id)
                .order_by(WorkerShift.shift_start.desc())
                .limit(max(1, min(int(limit), 100)))
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_shift(row) for row in rows]


async def start_worker_shift(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    existing = await _active_shift(db, worker_id)
    if existing is not None:
        return _serialize_shift(existing)
    shift = WorkerShift(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        shift_start=utc_now(),
        shift_type=str(payload.get("shift_type") or _default_shift_type(worker)).strip(),
        status="active",
        open_items=[],
        completed_items=[],
    )
    db.add(shift)
    await db.commit()
    return _serialize_shift(shift)


async def handover_worker_shift(
    db: AsyncSession,
    *,
    worker_id: str,
    shift_id: str,
    current_user: User,
    payload: dict[str, Any],
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    shift = await db.get(WorkerShift, shift_id)
    if shift is None or shift.worker_id != worker.id:
        raise HTTPException(status_code=404, detail="Worker shift not found")
    if shift.status != "active":
        return _serialize_shift(shift)
    shift.shift_end = utc_now()
    shift.open_items = await _collect_open_items(db, worker, shift.shift_start)
    shift.completed_items = await _collect_completed_items(db, worker, shift.shift_start or utc_now())
    shift.escalations_count = sum(1 for item in shift.open_items if item.get("type") == "monitor_alert")
    shift.autonomous_actions_count = sum(1 for item in shift.completed_items if item.get("type") == "trust_success")
    shift.handover_summary = (payload.get("handover_summary") or "").strip() or await _build_handover_summary(
        db,
        worker=worker,
        shift=shift,
        open_items=list(shift.open_items or []),
        completed_items=list(shift.completed_items or []),
    )
    requested_status = str(payload.get("status") or "handed_over").strip().lower()
    shift.status = requested_status if requested_status in {"completed", "handed_over"} else "handed_over"
    await db.commit()
    return _serialize_shift(shift)


async def generate_daily_agenda_for_worker(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    target_date: date | None = None,
) -> dict[str, Any]:
    agenda_date = target_date or _local_date(worker)
    existing = (
        await db.execute(
            select(WorkerDailyAgenda)
            .where(WorkerDailyAgenda.worker_id == worker.id, WorkerDailyAgenda.date == agenda_date)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _serialize_agenda(existing)

    items: list[dict[str, Any]] = []
    latest_shift = await _latest_shift(db, worker.id)
    if latest_shift and latest_shift.open_items:
        for entry in latest_shift.open_items:
            data = dict(entry)
            items.append(
                {
                    "priority": int(data.get("priority") or 1),
                    "type": data.get("type") or "handover_open_item",
                    "description": data.get("description") or data.get("title") or "Follow up previous shift item",
                    "source": "shift_handover",
                }
            )
    for monitor in worker.monitors or []:
        if not monitor.is_active:
            continue
        items.append(
            {
                "priority": 2,
                "type": "monitor",
                "description": f"Review monitor '{monitor.name}' ({monitor.monitor_type}).",
                "source": "worker_monitor",
            }
        )
    if worker.schedule_type != "always_on":
        items.append(
            {
                "priority": 3,
                "type": "shift_check",
                "description": f"Confirm {worker.schedule_type} shift coverage and handover readiness.",
                "source": "worker_schedule",
            }
        )
    if worker.report_schedule:
        items.append(
            {
                "priority": 4,
                "type": "report",
                "description": f"Prepare scheduled report for '{worker.report_schedule}'.",
                "source": "worker_reporting",
            }
        )
    if not items:
        items.append(
            {
                "priority": 2,
                "type": "monitor",
                "description": "Review worker health, unresolved alerts and current task slots.",
                "source": "default",
            }
        )
    items.sort(key=lambda item: (int(item.get("priority") or 99), str(item.get("description") or "")))
    agenda = WorkerDailyAgenda(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        date=agenda_date,
        agenda_items=items[:12],
        status="pending",
    )
    db.add(agenda)
    await db.commit()
    return _serialize_agenda(agenda)


async def get_worker_daily_agenda(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    day: date | None = None,
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    return await generate_daily_agenda_for_worker(db, worker=worker, target_date=day)


async def process_due_worker_agendas(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    counters = {"workers_checked": 0, "agendas_created": 0, "shifts_started": 0}
    async with session_factory() as db:
        workers = (
            (
                await db.execute(
                    select(AgentWorker)
                    .options(
                        selectinload(AgentWorker.monitors),
                        selectinload(AgentWorker.runtime_state),
                        selectinload(AgentWorker.onboarding),
                    )
                    .where(AgentWorker.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        for worker in workers:
            counters["workers_checked"] += 1
            local_today = _local_date(worker)
            agenda_exists = (
                await db.execute(
                    select(WorkerDailyAgenda.id).where(
                        WorkerDailyAgenda.worker_id == worker.id,
                        WorkerDailyAgenda.date == local_today,
                    )
                )
            ).scalar_one_or_none()
            if agenda_exists is None:
                await generate_daily_agenda_for_worker(db, worker=worker, target_date=local_today)
                counters["agendas_created"] += 1
            if _is_within_work_hours(worker):
                active = await _active_shift(db, worker.id)
                if active is None:
                    db.add(
                        WorkerShift(
                            id=str(uuid.uuid4()),
                            worker_id=worker.id,
                            shift_start=utc_now(),
                            shift_type=_default_shift_type(worker),
                            status="active",
                            open_items=[],
                            completed_items=[],
                        )
                    )
                    counters["shifts_started"] += 1
        await db.commit()
    return counters


class WorkerAgendaWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 300):
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            try:
                await process_due_worker_agendas(self._session_factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker agenda worker iteration failed")
            await asyncio.sleep(self._interval_seconds)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="worker-agenda-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
