"""Context builder of the admin tasks page: the user's tasks, their latest runs and the selected task's run log."""

import logging

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    Project,
    Task,
    TaskRun,
    User,
)
from ...services.agent_mode import list_agent_modes, serialize_agent_mode

logger = logging.getLogger(__name__)

__all__ = [
    "_build_tasks_context",
]


async def _task_rows(db: AsyncSession, tasks: list[Task]) -> list[dict]:
    task_rows = []
    for task in tasks:
        runs = (
            (
                await db.execute(
                    select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at.desc()).limit(1)
                )
            )
            .scalars()
            .all()
        )
        latest_run = runs[0] if runs else None
        project = await db.get(Project, task.project_id) if task.project_id else None
        task_rows.append(
            {
                "id": task.id,
                "name": task.name,
                "description": task.description or "",
                "task_type": task.task_type,
                "agent_type": task.agent_type,
                "schedule": task.schedule or "",
                "project_name": project.name if project else "No project",
                "config": task.config or {},
                "is_active": bool(task.is_active),
                "latest_run_status": latest_run.status if latest_run else "",
                "latest_run_started_at": latest_run.started_at if latest_run else None,
            }
        )
    return task_rows


def _steps_with_session_links(raw_steps: list) -> list[dict]:
    steps_log = []
    for s in raw_steps:
        step = dict(s)
        session_links = [
            {"session_id": sid, "url": f"/chat?session_id={sid}"}
            for sid in (step.get("session_ids") or [])
        ]
        step["session_links"] = session_links
        steps_log.append(step)
    return steps_log


def _run_duration_seconds(run: TaskRun) -> int | None:
    duration_s = None
    if run.started_at and run.completed_at:
        try:
            duration_s = int((run.completed_at - run.started_at).total_seconds())
        except Exception:
            logger.warning(
                "Failed to compute task run duration",
                extra={"task_run_id": run.id},
                exc_info=True,
            )
    return duration_s


def _serialize_task_run(run: TaskRun) -> dict:
    output = run.output or {}
    return {
        "id": run.id,
        "status": run.status,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_s": _run_duration_seconds(run),
        "session_id": run.session_id,
        "session_url": f"/chat?session_id={run.session_id}" if run.session_id else "",
        "error": run.error or "",
        "steps_log": _steps_with_session_links(run.steps_log or []),
        "processed_tickets": output.get("processed_tickets") or [],
        "skipped_tickets": output.get("skipped_tickets") or [],
        "raw_output": output,
    }


async def _selected_task_runs(db: AsyncSession, selected_task: Task | None) -> list[dict]:
    if not selected_task:
        return []
    runs = (
        (
            await db.execute(
                select(TaskRun)
                .where(TaskRun.task_id == selected_task.id)
                .order_by(TaskRun.started_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return [_serialize_task_run(run) for run in runs]


async def _build_tasks_context(
    request: Request,
    db: AsyncSession,
    *,
    user: User,
    task_id: str | None = None,
) -> dict:
    from app.services.agent_definition_payload import serialize_agent_definition_payload

    from .control_plane import _list_agent_definitions

    projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    agent_modes = [serialize_agent_mode(mode) for mode in list_agent_modes()]
    agents = await _list_agent_definitions(db, user_id=user.id)
    tasks = (
        (await db.execute(select(Task).where(Task.owner_id == user.id).order_by(Task.created_at.desc())))
        .scalars()
        .all()
    )
    selected_task = next((task for task in tasks if task.id == task_id), None)
    if not selected_task and tasks:
        selected_task = tasks[0]
    task_rows = await _task_rows(db, tasks)
    selected_task_runs = await _selected_task_runs(db, selected_task)
    return {
        "request": request,
        "user": user,
        "tasks": task_rows,
        "selected_task": {
            "id": selected_task.id,
            "name": selected_task.name,
            "description": selected_task.description or "",
            "task_type": selected_task.task_type,
            "schedule": selected_task.schedule or "",
            "config": selected_task.config or {},
            "is_active": bool(selected_task.is_active),
        }
        if selected_task
        else None,
        "selected_task_runs": selected_task_runs,
        "projects": projects,
        "agent_modes": agent_modes,
        "agents": [serialize_agent_definition_payload(agent) for agent in agents if agent.is_active],
    }
