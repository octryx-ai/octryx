"""The scheduler task of a Jira intake configuration and the normalized sync options it runs with."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import (
    Scheduler,
    Task,
    User,
    WorkItemSyncConfig,
)
from ....models.project.task import TASK_DEFINITION_BINDING
from ..intake.schedule import ScheduleError, cron_of, with_schedule
from ..jira_values import object_value, optional_int, string_list

WORK_JIRA_SYNC_TASK_TYPE = "secure_work_jira_sync"
DEFAULT_JIRA_SYNC_CRON = "*/15 * * * *"


def normalize_jira_sync_options(raw_options: dict[str, Any]) -> dict[str, Any]:
    options = object_value(raw_options)
    # One schedule value (a preset, or a custom cron).
    try:
        options = with_schedule(options, options.get("schedule") if "schedule" in options else None)
    except ScheduleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    for key in ["max_results", "manual_limit"]:
        value = optional_int(options.get(key))
        if value is not None:
            options[key] = max(1, min(value, 5000))

    automation_labels = string_list(options.get("automation_labels"))
    options["automation_labels"] = automation_labels or ["octryx"]
    exclude_labels = string_list(options.get("automation_exclude_labels"))
    if exclude_labels:
        options["automation_exclude_labels"] = exclude_labels
    mode = str(options.get("automation_mode") or "").strip()
    if mode:
        options["automation_mode"] = mode
    return options


async def sync_jira_work_item_scheduler(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    current_user: User,
) -> dict[str, Any]:
    sync_options = normalize_jira_sync_options(config.sync_options_json or {})
    config.sync_options_json = sync_options
    task = await _get_or_create_sync_task(db, config=config, current_user=current_user, sync_options=sync_options)
    scheduler = await _get_or_create_sync_scheduler(db, task=task, config=config, current_user=current_user)
    cron_expression = cron_of(sync_options["schedule"])
    scheduler.cron_expression = cron_expression or DEFAULT_JIRA_SYNC_CRON
    if cron_expression and config.is_active:
        scheduler.is_active = True
        task.is_active = True
    else:
        scheduler.is_active = False
    await db.flush()
    return {"task_id": task.id, "scheduler_id": scheduler.id}


async def _get_or_create_sync_task(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    current_user: User,
    sync_options: dict[str, Any],
) -> Task:
    task_config = {
        "sync_config_id": config.id,
        "limit": (
            optional_int(sync_options.get("max_results"))
            or optional_int(sync_options.get("manual_limit"))
            or 1000
        ),
        "local_execution": "deterministic",
        "requires_worker": False,
        "required_domain": "jira",
    }
    candidates = (
        await db.execute(select(Task).where(Task.task_type == WORK_JIRA_SYNC_TASK_TYPE))
    ).scalars().all()
    task = next((row for row in candidates if str((row.config or {}).get("sync_config_id") or "") == config.id), None)
    if task is None:
        task = Task(
            name=f"Jira Work Sync · {config.name}",
            description=f"Scheduled Jira Work Item sync for {config.name}.",
            task_type=WORK_JIRA_SYNC_TASK_TYPE,
            agent_type="operations",
            project_id=config.project_id,
            config=task_config,
            owner_id=current_user.id,
            is_active=config.is_active,
            dispatch_binding=TASK_DEFINITION_BINDING,
        )
        db.add(task)
        await db.flush()
    else:
        task.name = f"Jira Work Sync · {config.name}"
        task.description = f"Scheduled Jira Work Item sync for {config.name}."
        task.project_id = config.project_id
        task.config = task_config
        task.owner_id = task.owner_id or current_user.id
        task.is_active = config.is_active
    return task


async def _get_or_create_sync_scheduler(
    db: AsyncSession,
    *,
    task: Task,
    config: WorkItemSyncConfig,
    current_user: User,
) -> Scheduler:
    scheduler = (
        await db.execute(
            select(Scheduler)
            .where(Scheduler.task_id == task.id)
            .order_by(Scheduler.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if scheduler is None:
        scheduler = Scheduler(
            name=f"Jira Work Sync · {config.name}",
            description=f"Runs the Jira Work Item sync config {config.name}.",
            cron_expression=DEFAULT_JIRA_SYNC_CRON,
            task_id=task.id,
            owner_id=current_user.id,
            is_active=False,
        )
        db.add(scheduler)
        await db.flush()
    else:
        scheduler.name = f"Jira Work Sync · {config.name}"
        scheduler.description = f"Runs the Jira Work Item sync config {config.name}."
        scheduler.owner_id = scheduler.owner_id or current_user.id
    return scheduler
