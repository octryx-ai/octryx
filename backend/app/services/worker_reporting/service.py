"""Canonical service surface for worker reporting."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from ...models import AgentWorker, User, WorkerEscalation, WorkerLearning, WorkerMonitorEvent, WorkerReport, WorkerShift
from ..team_notification import create_notification
from .utils import (
    _admin_targets,
    _extract_learnings,
    _get_worker,
    _report_window,
    _require_admin,
    _serialize_learning,
    _serialize_report,
)

logger = logging.getLogger(__name__)


async def generate_worker_report(
    db: AsyncSession,
    *,
    worker: AgentWorker,
    report_type: str = "daily",
) -> dict[str, Any]:
    period_start, period_end = _report_window(worker)
    existing = (
        await db.execute(
            select(WorkerReport)
            .where(
                WorkerReport.worker_id == worker.id,
                WorkerReport.report_type == report_type,
                WorkerReport.period_start == period_start,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _serialize_report(existing)

    monitor_rows = (
        (
            await db.execute(
                select(WorkerMonitorEvent).where(
                    WorkerMonitorEvent.worker_id == worker.id,
                    WorkerMonitorEvent.created_at >= period_start,
                    WorkerMonitorEvent.created_at <= period_end,
                )
            )
        )
        .scalars()
        .all()
    )
    escalation_rows = (
        (
            await db.execute(
                select(WorkerEscalation).where(
                    WorkerEscalation.worker_id == worker.id,
                    WorkerEscalation.created_at >= period_start,
                    WorkerEscalation.created_at <= period_end,
                )
            )
        )
        .scalars()
        .all()
    )
    shift_rows = (
        (
            await db.execute(
                select(WorkerShift).where(
                    WorkerShift.worker_id == worker.id,
                    WorkerShift.shift_start >= period_start,
                    WorkerShift.shift_start <= period_end,
                )
            )
        )
        .scalars()
        .all()
    )

    learnings = await _extract_learnings(db, worker=worker, period_start=period_start, period_end=period_end)
    # Worker learnings are not promoted into any knowledge or memory store, so a report
    # creates no knowledge entries and no memory updates.
    knowledge_created = 0
    memory_updates = 0

    incidents_detected = len(monitor_rows)
    incidents_resolved = sum(1 for row in monitor_rows if row.resolved_at is not None)
    incidents_escalated = len(escalation_rows)
    autonomous_actions_taken = sum(
        1 for row in shift_rows for item in row.completed_items or [] if item.get("type") == "trust_success"
    )
    highlights = [
        {
            "type": "resolved" if row.resolved_at else "detected",
            "title": f"{row.severity.upper()} monitor event",
            "description": row.resolution_summary or f"Detected via {row.triggered_action or 'log'}",
        }
        for row in monitor_rows[:5]
    ]
    concerns = [
        {
            "type": "escalation",
            "title": row.reason[:120],
            "description": row.context_summary or "",
        }
        for row in escalation_rows[:5]
    ]
    recommendations = [
        {
            "action": "promote_learning",
            "reason": row.learning_content[:240],
            "confidence": float(row.confidence or 0.0),
        }
        for row in learnings[:5]
    ]
    summary = (
        f"{worker.name} completed the {report_type} report with {incidents_detected} detected incidents, "
        f"{incidents_resolved} resolved incidents and {incidents_escalated} escalations."
    )

    delivered_to: list[str] = []
    delivery_status = "pending"
    if worker.report_channel:
        targets = [worker.escalation_user] if worker.escalation_user else await _admin_targets(db)
        for target in targets[:1]:
            await create_notification(
                db,
                user_id=target.id,
                notification_type="worker.report.ready",
                title=f"Worker report: {worker.name}",
                body=summary,
                link="/chat",
            )
        delivered_to.append(worker.report_channel)
        delivery_status = "sent"

    row = WorkerReport(
        id=str(uuid.uuid4()),
        worker_id=worker.id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        summary=summary,
        incidents_detected=incidents_detected,
        incidents_resolved=incidents_resolved,
        incidents_escalated=incidents_escalated,
        autonomous_actions_taken=autonomous_actions_taken,
        knowledge_entries_created=knowledge_created,
        memory_updates=memory_updates,
        highlights=highlights,
        concerns=concerns,
        recommendations=recommendations,
        delivery_status=delivery_status,
        delivered_to=delivered_to,
    )
    db.add(row)
    await db.commit()
    return _serialize_report(row)


async def list_worker_reports(
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
                select(WorkerReport)
                .where(WorkerReport.worker_id == worker_id)
                .order_by(WorkerReport.period_start.desc())
                .limit(max(1, min(int(limit), 100)))
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_report(row) for row in rows]


async def create_worker_report(
    db: AsyncSession,
    *,
    worker_id: str,
    current_user: User,
    report_type: str = "daily",
) -> dict[str, Any]:
    await _require_admin(db, current_user)
    worker = await _get_worker(db, worker_id)
    return await generate_worker_report(db, worker=worker, report_type=report_type)


async def list_worker_learnings(
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
                select(WorkerLearning)
                .where(WorkerLearning.worker_id == worker_id)
                .order_by(WorkerLearning.created_at.desc())
                .limit(max(1, min(int(limit), 200)))
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_learning(row) for row in rows]


async def process_due_worker_reports(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    counters = {"workers_checked": 0, "reports_created": 0, "learnings_created": 0}
    async with session_factory() as db:
        workers = (
            (
                await db.execute(
                    select(AgentWorker).options(selectinload(AgentWorker.reports)).where(AgentWorker.is_active)
                )
            )
            .scalars()
            .all()
        )
        for worker in workers:
            counters["workers_checked"] += 1
            period_start, _ = _report_window(worker)
            existing = (
                await db.execute(
                    select(WorkerReport.id).where(
                        WorkerReport.worker_id == worker.id,
                        WorkerReport.report_type == "daily",
                        WorkerReport.period_start == period_start,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                before = len(
                    (await db.execute(select(WorkerLearning.id).where(WorkerLearning.worker_id == worker.id)))
                    .scalars()
                    .all()
                )
                report = await generate_worker_report(db, worker=worker, report_type="daily")
                counters["reports_created"] += 1 if report else 0
                after_rows = (
                    (
                        await db.execute(
                            select(WorkerLearning).where(
                                WorkerLearning.worker_id == worker.id,
                                WorkerLearning.created_at >= period_start,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                counters["learnings_created"] += len(after_rows) - before
        await db.commit()
    return counters


class WorkerReportWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 300):
        self._session_factory = session_factory
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            try:
                await process_due_worker_reports(self._session_factory)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Worker report worker iteration failed")
            await asyncio.sleep(self._interval_seconds)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="worker-report-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None


__all__ = [
    "WorkerReportWorker",
    "create_worker_report",
    "generate_worker_report",
    "list_worker_learnings",
    "list_worker_reports",
    "process_due_worker_reports",
]
