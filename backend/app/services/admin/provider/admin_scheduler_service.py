"""Admin-panel service helpers for scheduler management flows.

A submitted cron expression is validated before any write; an update that omits it keeps
the stored value, even one that would not validate.

List, create and update responses carry ``worker_application``: whether the scheduling worker
has registered exactly this row (``paused|pending|applied|worker_unavailable|invalid_schedule``,
``next_run_at`` UTC ISO or null, ``timezone`` or null). It describes registration, not task
execution, and is computed in one batch for a list. Saving only records the row; the worker applies
it through reconciliation, so a fresh save normally reads ``pending``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import Project, Task
from ....models.project.scheduler import Scheduler


async def _require_schedulable_cron(expression: Any) -> None:
    # Imported lazily: the scheduler package imports the agent engine, which imports this module.
    from ....scheduler.dispatch.cron_schedule import require_schedulable_cron

    await require_schedulable_cron(expression)


async def _worker_applications(db: AsyncSession, schedulers: list[Scheduler]) -> dict[str, dict[str, Any]]:
    # Imported lazily: the scheduler package imports the agent engine, which imports this module.
    from ....scheduler.coordination.application_status import scheduler_worker_applications

    return await scheduler_worker_applications(db, schedulers)


def serialize_scheduler(
    scheduler: Scheduler, task: Task | None = None, worker_application: dict[str, Any] | None = None
) -> dict[str, Any]:
    loaded_task = task if task is not None else scheduler.__dict__.get("task")
    payload = {
        "id": scheduler.id,
        "name": scheduler.name,
        "description": scheduler.description or "",
        "cron_expression": scheduler.cron_expression,
        "task_id": scheduler.task_id,
        "task_name": loaded_task.name if loaded_task else "",
        "is_active": scheduler.is_active,
        "owner_id": scheduler.owner_id,
        "created_at": scheduler.created_at.isoformat() if scheduler.created_at else None,
    }
    if worker_application is not None:
        payload["worker_application"] = worker_application
    return payload


async def list_schedulers(db: AsyncSession) -> list[dict[str, Any]]:
    from ...automation_schedule_view import is_work_intake_task, last_runs, next_run_at, schedule_in_words

    result = await db.execute(
        select(Scheduler).options(selectinload(Scheduler.task)).order_by(Scheduler.created_at.desc())
    )
    schedulers = list(result.scalars().all())
    applications = await _worker_applications(db, schedulers)
    action_scheduled = (await db.execute(select(Task).where(Task.schedule.is_not(None)))).scalars().all()
    runs = await last_runs(db, sorted({s.task_id for s in schedulers} | {t.id for t in action_scheduled}))
    workspaces = dict((await db.execute(select(Project.id, Project.name))).all())
    rows: list[dict[str, Any]] = []
    for scheduler in schedulers:
        task = scheduler.__dict__.get("task")
        payload = serialize_scheduler(scheduler, worker_application=applications.get(scheduler.id))
        # In words, with the last and next run; Work-intake jobs are owned by Work → Intake.
        payload.update({
            "kind": "scheduler",
            "schedule_words": schedule_in_words(scheduler.cron_expression),
            "next_run": next_run_at(scheduler.cron_expression) if scheduler.is_active else None,
            "last_run": runs.get(scheduler.task_id),
            "workspace_name": workspaces.get(task.project_id, "") if task else "",
            "managed_by_work": bool(task and is_work_intake_task(task)),
            "read_only": bool(task and is_work_intake_task(task)),
        })
        rows.append(payload)
    for task in action_scheduled:
        # The cron set on the Action itself (REST, admin task writer, package import) fires next to its Scheduler rows;
        # it is edited on the Action, so it reads read-only here.
        rows.append({
            "id": f"action-schedule:{task.id}", "kind": "action_schedule", "name": task.name,
            "description": "", "cron_expression": task.schedule, "task_id": task.id, "task_name": task.name,
            "is_active": bool(task.is_active), "owner_id": task.owner_id, "created_at": None,
            "schedule_words": schedule_in_words(task.schedule),
            "next_run": next_run_at(task.schedule) if task.is_active else None,
            "last_run": runs.get(task.id), "workspace_name": workspaces.get(task.project_id, ""),
            "managed_by_work": is_work_intake_task(task), "read_only": True,
        })
    return rows


async def create_scheduler(db: AsyncSession, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    cron_expression = str(payload.get("cron_expression") or "").strip()
    task_id = str(payload.get("task_id") or "").strip()
    if not name or not cron_expression or not task_id:
        raise HTTPException(status_code=400, detail="name, cron_expression, task_id required")
    await _require_schedulable_cron(cron_expression)

    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    scheduler = Scheduler(
        name=name,
        description=str(payload.get("description") or ""),
        cron_expression=cron_expression,
        task_id=task_id,
        is_active=bool(payload.get("is_active", True)),
        owner_id=user_id,
    )
    db.add(scheduler)
    await db.commit()
    await db.refresh(scheduler)

    from ....runtime_lifecycle import get_task_scheduler

    get_task_scheduler().request_reconcile()
    applications = await _worker_applications(db, [scheduler])
    return serialize_scheduler(scheduler, task, applications.get(scheduler.id))


async def update_scheduler(db: AsyncSession, *, scheduler_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.id == scheduler_id))).scalar_one_or_none()
    if not scheduler:
        raise HTTPException(status_code=404, detail="Scheduler not found")
    if "cron_expression" in payload:
        await _require_schedulable_cron(payload["cron_expression"])
    if "task_id" in payload:
        task_exists = (await db.execute(select(Task.id).where(Task.id == payload["task_id"]))).scalar_one_or_none()
        if task_exists is None:
            raise HTTPException(status_code=404, detail="Task not found")

    for field in ["name", "description", "cron_expression", "task_id", "is_active"]:
        if field in payload:
            setattr(scheduler, field, payload[field])
    await db.commit()
    await db.refresh(scheduler)

    from ....runtime_lifecycle import get_task_scheduler

    get_task_scheduler().request_reconcile()
    task = (await db.execute(select(Task).where(Task.id == scheduler.task_id))).scalar_one_or_none()
    applications = await _worker_applications(db, [scheduler])
    return serialize_scheduler(scheduler, task, applications.get(scheduler.id))


async def preview_scheduler(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculated next fire times; reads no rows and registers no job."""
    from ....scheduler.dispatch.cron_schedule import preview_schedule

    return await preview_schedule(payload.get("cron_expression"), payload.get("count", 5))


async def delete_scheduler(db: AsyncSession, *, scheduler_id: str) -> dict[str, Any]:
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.id == scheduler_id))).scalar_one_or_none()
    if not scheduler:
        raise HTTPException(status_code=404, detail="Scheduler not found")

    from ....runtime_lifecycle import get_task_scheduler

    await db.delete(scheduler)
    await db.commit()
    # After the commit: the guarded fire already refuses the deleted row; this only asks the owner to drop the job.
    get_task_scheduler().request_reconcile()
    return {"status": "deleted"}
