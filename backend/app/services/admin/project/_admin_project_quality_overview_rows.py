"""Bulk row loading and row serialization for the admin projects quality overview."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import AgentDefinition, Task, TaskRun
from ....models.project.scheduler import Scheduler
from ...error_facts import error_facts
from ..provider.admin_scheduler_service import serialize_scheduler
from ..task.admin_task_service import serialize_task_with_stats
from .admin_project_quality_catalog import serialize_project_agent_catalog

# Records keep the overview's logger name, so existing log filters and alerts still match.
logger = logging.getLogger("app.services.admin.project.admin_project_quality_overview")


@dataclass
class OverviewRows:
    """Rows shared by every project of one overview, each grouped by its owner id."""

    trace_sync_tasks_by_project: dict[str, list[Task]] = field(default_factory=dict)
    schedulers_by_task_id: dict[str, list[Scheduler]] = field(default_factory=dict)
    trace_sync_runs_by_task_id: dict[str, list[TaskRun]] = field(default_factory=dict)
    project_agents_by_project: dict[str, list[AgentDefinition]] = field(default_factory=dict)


def _overview_error(section: str, exc: Exception) -> dict[str, str]:
    """A partial overview names the section and the error class; the exception text is never returned."""
    return {"section": section, **error_facts("overview_section_failed", exc)}


async def _safe_scalars(
    db: AsyncSession,
    statement: Any,
    *,
    section: str,
    errors: list[dict[str, str]],
    unique: bool = False,
) -> list[Any]:
    try:
        scalars = (await db.execute(statement)).scalars()
        if unique:
            scalars = scalars.unique()
        return list(scalars.all())
    except Exception as exc:
        logger.exception("Optional admin projects overview query failed", extra={"section": section})
        errors.append(_overview_error(section, exc))
        await db.rollback()
        return []


async def load_overview_rows(
    db: AsyncSession, *, project_ids: list[str], errors: list[dict[str, str]]
) -> OverviewRows:
    rows = OverviewRows()
    task_rows = await _safe_scalars(
        db,
        select(Task).where(Task.project_id.is_not(None)).order_by(Task.created_at.desc()),
        section="project_tasks",
        errors=errors,
    )
    for task in task_rows:
        config = dict(task.config or {}) if isinstance(task.config, dict) else {}
        if str(config.get("design_trace_sync_workflow_id") or "").strip() and task.project_id:
            rows.trace_sync_tasks_by_project.setdefault(task.project_id, []).append(task)

    scheduler_rows = await _safe_scalars(
        db,
        select(Scheduler).order_by(Scheduler.created_at.desc()),
        section="schedulers",
        errors=errors,
    )
    for row in scheduler_rows:
        rows.schedulers_by_task_id.setdefault(str(row.task_id), []).append(row)

    await _load_trace_sync_runs(db, rows, errors=errors)
    if project_ids:
        await _load_project_agents(db, rows, project_ids=project_ids, errors=errors)
    return rows


async def _load_trace_sync_runs(db: AsyncSession, rows: OverviewRows, *, errors: list[dict[str, str]]) -> None:
    trace_task_ids = [task.id for tasks in rows.trace_sync_tasks_by_project.values() for task in tasks]
    if not trace_task_ids:
        return
    trace_run_rows = await _safe_scalars(
        db,
        select(TaskRun).where(TaskRun.task_id.in_(trace_task_ids)).order_by(TaskRun.started_at.desc()),
        section="design_trace_task_runs",
        errors=errors,
    )
    for row in trace_run_rows:
        bucket = rows.trace_sync_runs_by_task_id.setdefault(str(row.task_id), [])
        if len(bucket) < 3:
            bucket.append(row)


async def _load_project_agents(
    db: AsyncSession, rows: OverviewRows, *, project_ids: list[str], errors: list[dict[str, str]]
) -> None:
    agent_rows = await _safe_scalars(
        db,
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(AgentDefinition.project_id.in_(project_ids), AgentDefinition.is_active.is_(True))
        .order_by(
            AgentDefinition.updated_at.desc(),
            AgentDefinition.created_at.desc(),
            AgentDefinition.name.asc(),
        ),
        section="project_agents",
        errors=errors,
        unique=True,
    )
    for row in agent_rows:
        if row.project_id:
            rows.project_agents_by_project.setdefault(row.project_id, []).append(row)


async def serialize_project_agents(
    agents: list[AgentDefinition],
    *,
    agent_preferences: dict[str, dict[str, Any]],
) -> list[dict[str, object]]:
    deduped_agents: list[dict[str, object]] = []
    seen_agent_keys: set[tuple[str, str]] = set()
    for agent in agents:
        dedupe_key = (str(agent.name or "").strip().lower(), str(agent.agent_type or "").strip().lower())
        if dedupe_key in seen_agent_keys:
            continue
        seen_agent_keys.add(dedupe_key)
        deduped_agents.append(
            serialize_project_agent_catalog(
                agent,
                preference_status=str((agent_preferences.get(agent.id) or {}).get("status") or ""),
            )
        )
    return deduped_agents


async def serialize_trace_sync_tasks(
    db: AsyncSession,
    *,
    trace_tasks: list[Task],
    trace_sync_runs_by_task_id: dict[str, list[TaskRun]],
) -> list[dict[str, object]]:
    trace_task_payloads: list[dict[str, object]] = []
    for task in trace_tasks:
        task_payload = await serialize_task_with_stats(db, task)
        task_payload["recent_runs"] = [
            {
                "id": run.id,
                "task_id": run.task_id,
                "session_id": run.session_id,
                "status": run.status,
                "started_by": run.started_by,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error": run.error,
                "duration_seconds": (
                    (run.completed_at - run.started_at).total_seconds()
                    if run.started_at and run.completed_at
                    else None
                ),
                "steps_log": run.steps_log,
            }
            for run in trace_sync_runs_by_task_id.get(task.id, [])
        ]
        trace_task_payloads.append(task_payload)
    return trace_task_payloads


async def serialize_trace_sync_schedulers(
    *,
    trace_tasks: list[Task],
    schedulers_by_task_id: dict[str, list[Scheduler]],
) -> list[dict[str, object]]:
    return [serialize_scheduler(row, task) for task in trace_tasks for row in schedulers_by_task_id.get(task.id, [])]
