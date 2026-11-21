"""Core task CRUD/run operations for admin task service."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project, Task, TaskQueueEntry, TaskRun, TaskStep
from ....models import Session as AgentSession
from ....models.integration.webhook import Webhook
from ...agent_mode.authoring import authored_agent_mode, require_explicit_agent_mode
from ...run_capability.schedule_capability import require_valid_schedule_capability
from ...task_schedule_authoring import require_task_schedule
from ._admin_task_serialization import serialize_task
from ._admin_task_stats import run_chronology_order, serialize_task_with_stats
from ._dispatch_binding import require_binding_value, require_bound_state
from ._queue_wait_reason import queue_wait_reason


async def list_tasks(db: AsyncSession) -> list[dict[str, Any]]:
    from ...automation_schedule_view import is_work_intake_task, started_by

    result = await db.execute(select(Task).order_by(Task.created_at.desc()))
    tasks = result.scalars().all()
    starts = await started_by(db)
    # What starts each Action, and whether Work → Intake owns it (read-only here).
    return [
        {**await serialize_task_with_stats(db, task), "started_by": starts.get(task.id, []),
         "managed_by_work": is_work_intake_task(task)}
        for task in tasks
    ]


async def create_task(db: AsyncSession, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    # An explicit choice (the admin form always sends its visible one) must name an active mode.
    agent_type = await authored_agent_mode(db, payload)

    # An Action always names its Workspace; no silent first-Workspace fallback.
    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        from ...run_admission.denials import workspace_required_detail

        raise HTTPException(status_code=422, detail=workspace_required_detail("Choose the Workspace this Action runs in."))
    if await db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")

    from ....time_utils import utc_now

    require_valid_schedule_capability(payload.get("config") or {})
    from ...run_admission.action_config import require_action_config

    await require_action_config(db, payload.get("config") or {})  # a workflow run or an agent, never both
    # Validated raw, so a non-string never becomes "no schedule" through truthiness.
    await require_task_schedule(payload.get("schedule"))
    # The binding is required and validated against the full new state before anything is written.
    dispatch_binding = require_binding_value(payload.get("dispatch_binding"))
    await require_bound_state(
        db, binding=dispatch_binding, task_type=payload.get("task_type", "agent_run"),
        config=payload.get("config") or {}, owner_id=user_id, project_id=project_id, has_enabled_steps=False,
    )
    task = Task(
        id=str(uuid.uuid4()),
        project_id=project_id,
        name=name,
        description=payload.get("description", ""),
        task_type=payload.get("task_type", "agent_run"),
        agent_type=agent_type,
        schedule=payload.get("schedule") or None,
        config=payload.get("config") or {},
        max_concurrent_agents=int(payload.get("max_concurrent_agents") or 3),
        is_active=payload.get("is_active", True),
        owner_id=user_id,
        created_at=utc_now(),
        dispatch_binding=dispatch_binding,
    )
    if "default_runtime_selector" in payload:
        task.default_runtime_selector = payload["default_runtime_selector"] or {}
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return serialize_task(
        task,
        run_count=0,
        running_count=0,
        queued_count=0,
        last_run=None,
        step_count=0,
        dependency_count=0,
        dependent_count=0,
        next_queue_priority=None,
    )


async def update_task(db: AsyncSession, *, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # Validated before any field changes; an update without agent_type keeps the stored value.
    agent_type = await require_explicit_agent_mode(db, payload["agent_type"]) if "agent_type" in payload else None

    allowed = (
        "name",
        "description",
        "task_type",
        "agent_type",
        "schedule",
        "config",
        "is_active",
        "max_concurrent_agents",
    )
    if "config" in payload:
        steps = (await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))).scalars().all()
        require_valid_schedule_capability(payload.get("config") or {}, steps)
        from ...run_admission.action_config import require_action_config

        await require_action_config(db, payload.get("config") or {})
    if "schedule" in payload:
        # An omitted schedule keeps the stored value; None/"" remove it; anything else must schedule.
        await require_task_schedule(payload["schedule"])
    # An omitted binding keeps the stored one. A save that sets the binding or changes what it
    # depends on (type, config) is validated as the effective new state.
    dispatch_binding = (
        require_binding_value(payload["dispatch_binding"]) if "dispatch_binding" in payload else task.dispatch_binding
    )
    if {"dispatch_binding", "task_type", "config"} & set(payload):
        from ....scheduler.dispatch.agent_definition_binding import has_enabled_steps

        await require_bound_state(
            db, binding=dispatch_binding, task_type=payload.get("task_type", task.task_type),
            config=payload["config"] if "config" in payload else task.config, owner_id=task.owner_id,
            project_id=task.project_id, has_enabled_steps=await has_enabled_steps(db, task.id),
        )
    for field in allowed:
        if field in payload:
            setattr(task, field, payload[field])
    if agent_type is not None:
        task.agent_type = agent_type
    if "default_runtime_selector" in payload:
        task.default_runtime_selector = payload["default_runtime_selector"] or {}
    task.dispatch_binding = dispatch_binding
    await db.commit()
    await db.refresh(task)
    return await serialize_task_with_stats(db, task)


async def delete_task(db: AsyncSession, *, task_id: str) -> dict[str, Any]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    runs = (await db.execute(select(TaskRun).where(TaskRun.task_id == task_id))).scalars().all()
    for run in runs:
        await db.delete(run)
    # A webhook that started this Action reads "needs setup" (its alerts wait, nothing guesses).
    await db.execute(update(Webhook).where(Webhook.task_id == task_id).values(task_id=None))
    await db.delete(task)
    await db.commit()
    return {"status": "deleted"}


async def trigger_task(*, task_id: str, db: AsyncSession) -> dict[str, Any]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalars().first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    from ....runtime_lifecycle import get_task_scheduler

    return await get_task_scheduler().run_task_now(task_id)


async def list_task_runs(db: AsyncSession, *, task_id: str) -> list[dict[str, Any]]:
    result = await db.execute(
        select(TaskRun, TaskQueueEntry)
        .outerjoin(TaskQueueEntry, TaskQueueEntry.task_run_id == TaskRun.id)
        .where(TaskRun.task_id == task_id)
        # The same chronology as the Action summary's "last run", with its tie rule.
        .order_by(*run_chronology_order())
        .limit(30)
    )
    runs = result.all()
    payloads: list[dict[str, Any]] = []
    for run, queue_entry in runs:
        duration = None
        if run.started_at and run.completed_at:
            duration = (run.completed_at - run.started_at).total_seconds()
        payloads.append(
            {
                "id": run.id,
                "task_id": run.task_id,
                "session_id": run.session_id,
                "status": run.status,
                "started_by": run.started_by,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "error": run.error,
                "duration_seconds": duration,
                "steps_log": run.steps_log or [],
                "queue_priority": queue_entry.priority if queue_entry else None,
                "queue_status": queue_entry.status if queue_entry else None,
                "queue_required_domain": queue_entry.required_domain if queue_entry else None,
                "queue_assigned_to": queue_entry.assigned_to if queue_entry else None,
                "queued_at": queue_entry.queued_at.isoformat() if queue_entry and queue_entry.queued_at else None,
                "queue_started_at": (
                    queue_entry.started_at.isoformat() if queue_entry and queue_entry.started_at else None
                ),
                "estimated_wait_seconds": queue_entry.estimated_wait_seconds if queue_entry else None,
                # A fixed safe code while the run is still waiting, never the raw last_error.
                "queue_wait_reason": queue_wait_reason(run.status, queue_entry),
            }
        )
    return payloads


async def cancel_task_run(db: AsyncSession, *, task_id: str, run_id: str) -> dict[str, Any]:
    task_run = (
        (await db.execute(select(TaskRun).where(TaskRun.id == run_id, TaskRun.task_id == task_id))).scalars().first()
    )
    if not task_run:
        raise HTTPException(status_code=404, detail="Run not found")

    from ....time_utils import utc_now

    task_run.status = "cancelled"
    task_run.completed_at = utc_now()
    queue_entry = (
        await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == task_run.id))
    ).scalar_one_or_none()
    if queue_entry and queue_entry.completed_at is None:
        queue_entry.completed_at = task_run.completed_at
    await db.commit()
    if task_run.session_id:
        from ...session.tree_cleanup import collect_session_descendants

        session_ids = await collect_session_descendants(db, task_run.session_id)
        sessions = (await db.execute(select(AgentSession).where(AgentSession.id.in_(session_ids)))).scalars().all()
        for session in sessions:
            if session.status not in ("archived",):
                session.status = "cancelled"
        await db.commit()
    from ....runtime_lifecycle import get_task_scheduler

    get_task_scheduler().cancel_task(task_id)
    return {"status": "cancelled"}
