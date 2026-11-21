from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from ...models import Role, SLABreach, SLADefinition, Task, TaskRun, User, UserRole
from ...services.team_notification import create_notification
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from ..problems.links import TARGET_TASKS, fix_link
from .common import (
    _normalize_agent_type,
    _normalize_threshold,
    _validate_task_id,
    build_sla_definition,
    serialize_sla_breach,
    serialize_sla_definition,
)

logger = logging.getLogger(__name__)


async def list_sla_definitions(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(SLADefinition).order_by(SLADefinition.created_at.desc()))).scalars().all()
    return [serialize_sla_definition(row) for row in rows]


async def create_sla_definition(db: AsyncSession, *, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = await _validate_task_id(db, payload.get("task_id"))
    agent_type = _normalize_agent_type(payload.get("agent_type"))
    row = build_sla_definition(payload=payload, task_id=task_id, agent_type=agent_type)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return serialize_sla_definition(row)


async def update_sla_definition(db: AsyncSession, *, definition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = await db.get(SLADefinition, definition_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SLA definition not found")
    if "name" in payload and payload.get("name") is not None:
        row.name = str(payload.get("name") or "").strip() or row.name
    if "task_id" in payload:
        row.task_id = await _validate_task_id(db, payload.get("task_id"))
    if "agent_type" in payload:
        row.agent_type = _normalize_agent_type(payload.get("agent_type"))
    if not row.task_id and not row.agent_type:
        raise HTTPException(status_code=422, detail="task_id or agent_type is required")
    if "max_duration_seconds" in payload and payload.get("max_duration_seconds") is not None:
        max_duration_seconds = int(payload.get("max_duration_seconds") or 0)
        if max_duration_seconds <= 0:
            raise HTTPException(status_code=422, detail="max_duration_seconds must be greater than 0")
        row.max_duration_seconds = max_duration_seconds
    if "alert_threshold" in payload and payload.get("alert_threshold") is not None:
        row.alert_threshold = _normalize_threshold(payload.get("alert_threshold"))
    if "is_active" in payload and payload.get("is_active") is not None:
        row.is_active = bool(payload.get("is_active"))
    row.updated_at = utc_now()
    await db.commit()
    await db.refresh(row)
    return serialize_sla_definition(row)


async def delete_sla_definition(db: AsyncSession, *, definition_id: str) -> dict[str, Any]:
    row = await db.get(SLADefinition, definition_id)
    if row is None:
        raise HTTPException(status_code=404, detail="SLA definition not found")
    await db.delete(row)
    await db.commit()
    return {"status": "deleted", "id": definition_id}


async def list_sla_breaches(
    db: AsyncSession,
    *,
    limit: int = 100,
    unresolved_only: bool = False,
) -> list[dict[str, Any]]:
    stmt = (
        select(SLABreach)
        .options(selectinload(SLABreach.sla_definition), selectinload(SLABreach.task_run))
        .order_by(SLABreach.created_at.desc())
        .limit(max(1, min(int(limit or 100), 500)))
    )
    if unresolved_only:
        stmt = stmt.where(SLABreach.is_resolved.is_(False))
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_sla_breach(row) for row in rows]


async def _task_run_candidates(db: AsyncSession) -> list[TaskRun]:
    stmt = (
        select(TaskRun)
        .join(Task, Task.id == TaskRun.task_id)
        .options(selectinload(TaskRun.task))
        .where(
            TaskRun.started_at.is_not(None),
            TaskRun.status.in_(("running", "completed", "failed", "cancelled", "skipped")),
        )
        .order_by(TaskRun.started_at.desc())
        .limit(500)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _matching_definition_map(db: AsyncSession, runs: list[TaskRun]) -> dict[str, SLADefinition]:
    if not runs:
        return {}
    task_ids = {run.task_id for run in runs if run.task_id}
    agent_types = {agent_type for run in runs if run.task and (agent_type := str(run.task.agent_type or "").strip())}
    definitions = (
        (
            await db.execute(
                select(SLADefinition).where(
                    SLADefinition.is_active.is_(True),
                    or_(
                        SLADefinition.task_id.in_(task_ids) if task_ids else False,
                        SLADefinition.agent_type.in_(agent_types) if agent_types else False,
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    by_task_id = {row.task_id: row for row in definitions if row.task_id}
    by_agent_type = {row.agent_type: row for row in definitions if row.agent_type and not row.task_id}
    mapping: dict[str, SLADefinition] = {}
    for run in runs:
        definition = by_task_id.get(run.task_id)
        if definition is None and run.task and run.task.agent_type:
            definition = by_agent_type.get(str(run.task.agent_type))
        if definition is not None:
            mapping[run.id] = definition
    return mapping


async def _existing_breach_types(db: AsyncSession, *, run_id: str, definition_id: str) -> set[str]:
    rows = await db.execute(
        select(SLABreach.breach_type).where(
            SLABreach.task_run_id == run_id,
            SLABreach.sla_definition_id == definition_id,
        )
    )
    return {str(row[0]) for row in rows.all()}


async def _notification_targets(db: AsyncSession, task: Task) -> list[str]:
    targets = {task.owner_id}
    rows = await db.execute(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.name == "admin", User.is_active)
    )
    for (user_id,) in rows.all():
        if user_id:
            targets.add(user_id)
    return [user_id for user_id in targets if user_id]


async def _create_breach(
    db: AsyncSession,
    *,
    definition: SLADefinition,
    run: TaskRun,
    breach_type: str,
    severity: str,
    expected_at,
    actual_at,
) -> SLABreach:
    row = SLABreach(
        id=str(uuid.uuid4()),
        sla_definition_id=definition.id,
        task_run_id=run.id,
        task_id=run.task_id,
        expected_at=expected_at,
        actual_at=actual_at,
        breach_type=breach_type,
        severity=severity,
        is_resolved=False,
        notification_sent=False,
    )
    db.add(row)
    await db.flush()
    return row


async def _notify_breach(db: AsyncSession, *, run: TaskRun, definition: SLADefinition, breach: SLABreach) -> None:
    if breach.notification_sent:
        return
    for user_id in await _notification_targets(db, run.task):
        await create_notification(
            db,
            user_id=user_id,
            notification_type="sla.breach",
            title=f"SLA {breach.severity}: {definition.name}",
            body=(f"Task '{run.task.name}' run {run.id[:8]} exceeded SLA ({breach.breach_type.replace('_', ' ')})."),
            link=fix_link(TARGET_TASKS, object_id=run.task_id)["href"],
            project_id=run.task.project_id,
            payload={
                "task_id": run.task_id,
                "task_run_id": run.id,
                "sla_definition_id": definition.id,
                "breach_type": breach.breach_type,
                "severity": breach.severity,
            },
        )
    breach.notification_sent = True


async def process_sla_breaches(db: AsyncSession) -> dict[str, Any]:
    now = utc_now_aware()
    runs = await _task_run_candidates(db)
    definition_map = await _matching_definition_map(db, runs)
    created: list[SLABreach] = []
    resolved = 0

    for run in runs:
        definition = definition_map.get(run.id)
        if definition is None or run.task is None or run.started_at is None:
            continue
        started_at = ensure_utc(run.started_at)
        if started_at is None:
            continue
        expected_at = started_at + timedelta(seconds=int(definition.max_duration_seconds or 0))
        warning_at = started_at + timedelta(
            seconds=max(1, int((definition.max_duration_seconds or 0) * float(definition.alert_threshold or 0.8)))
        )
        existing = await _existing_breach_types(db, run_id=run.id, definition_id=definition.id)
        completed_at = ensure_utc(run.completed_at)

        if completed_at is not None:
            open_rows = (
                (
                    await db.execute(
                        select(SLABreach).where(
                            SLABreach.task_run_id == run.id,
                            SLABreach.sla_definition_id == definition.id,
                            SLABreach.is_resolved.is_(False),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in open_rows:
                if row.breach_type == "warning_threshold" and completed_at <= expected_at:
                    row.is_resolved = True
                    row.resolved_at = now
                    resolved += 1
            if completed_at > expected_at and "duration_exceeded" not in existing:
                breach = await _create_breach(
                    db,
                    definition=definition,
                    run=run,
                    breach_type="duration_exceeded",
                    severity="critical",
                    expected_at=expected_at,
                    actual_at=completed_at,
                )
                await _notify_breach(db, run=run, definition=definition, breach=breach)
                created.append(breach)
            continue

        if now >= warning_at and "warning_threshold" not in existing:
            breach = await _create_breach(
                db,
                definition=definition,
                run=run,
                breach_type="warning_threshold",
                severity="warning",
                expected_at=warning_at,
                actual_at=now,
            )
            await _notify_breach(db, run=run, definition=definition, breach=breach)
            created.append(breach)
            existing.add("warning_threshold")

        if now >= expected_at and "duration_exceeded" not in existing:
            breach = await _create_breach(
                db,
                definition=definition,
                run=run,
                breach_type="duration_exceeded",
                severity="critical",
                expected_at=expected_at,
                actual_at=now,
            )
            await _notify_breach(db, run=run, definition=definition, breach=breach)
            created.append(breach)

    await db.commit()
    return {
        "checked_runs": len(runs),
        "definitions_matched": len(definition_map),
        "breaches_created": len(created),
        "breaches_resolved": resolved,
        "breaches": [serialize_sla_breach(row) for row in created],
    }


class SLAMonitorWorker:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 60) -> None:
        self._session_factory = session_factory
        self._interval_seconds = max(15, int(interval_seconds))
        self._task: asyncio.Task | None = None
        self.last_result: dict[str, Any] = {
            "checked_runs": 0,
            "definitions_matched": 0,
            "breaches_created": 0,
            "breaches_resolved": 0,
        }

    async def _run_once(self) -> None:
        async with self._session_factory() as db:
            self.last_result = await process_sla_breaches(db)

    async def _loop(self) -> None:
        while True:
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("SLA monitor worker run failed")
            await asyncio.sleep(self._interval_seconds)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="sla-monitor-worker")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
