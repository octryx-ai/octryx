"""Create a scheduled task that runs one design trace sync workflow."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.admin.task._admin_task_management import create_task
from app.services.admin.task._admin_task_stats import serialize_task_with_stats as _serialize_task_with_stats

from ...models import Task, TaskStep
from ...models.project.task import TASK_DEFINITION_BINDING
from ..admin.provider.admin_scheduler_service import create_scheduler
from .project_workflow import load_project_workflow

CreateTaskFn = Callable[..., Awaitable[dict[str, Any]]]
SerializeTaskFn = Callable[..., Awaitable[dict[str, Any]]]
CreateSchedulerFn = Callable[..., Awaitable[dict[str, Any]]]


async def create_design_trace_sync_workflow_task(
    db: AsyncSession,
    *,
    project_id: str,
    workflow_id: str,
    user_id: str,
    payload: dict[str, Any] | None = None,
    create_task_func: CreateTaskFn = create_task,
    serialize_task_with_stats_func: SerializeTaskFn = _serialize_task_with_stats,
    create_scheduler_func: CreateSchedulerFn = create_scheduler,
) -> dict[str, Any]:
    workflow = await load_project_workflow(db, project_id=project_id, workflow_id=workflow_id)
    raw_payload = dict(payload or {})
    task_name, task_description, cron_expression = await _schedule_fields(raw_payload, workflow)
    is_active = bool(raw_payload.get("is_active", True))
    limit_per_repository = _limit_per_repository(raw_payload, workflow)
    task_payload = await create_task_func(
        db,
        user_id=user_id,
        payload={
            "project_id": project_id,
            "name": task_name,
            "description": task_description,
            "task_type": "agent_run",
            "agent_type": "documentation",
            "config": {
                "design_trace_sync_workflow_id": workflow_id,
                "design_trace_sync_source_kind": workflow.get("source_kind"),
                "design_trace_sync_auto_created": True,
            },
            "is_active": is_active,
            "max_concurrent_agents": 1,
            # The sync runs its own fetch/output step pipeline.
            "dispatch_binding": TASK_DEFINITION_BINDING,
        },
    )
    task = (await db.execute(select(Task).where(Task.id == task_payload["id"]))).scalar_one()
    await _add_sync_steps(
        db, task, workflow, project_id=project_id, workflow_id=workflow_id, limit_per_repository=limit_per_repository
    )

    scheduler = await create_scheduler_func(
        db,
        user_id=user_id,
        payload={
            "name": str(raw_payload.get("scheduler_name") or f"{workflow['name']} Schedule").strip()
            or f"{workflow['name']} Schedule",
            "description": str(raw_payload.get("scheduler_description") or task_description).strip(),
            "cron_expression": cron_expression,
            "task_id": task.id,
            "is_active": is_active,
        },
    )
    return {
        "project_id": project_id,
        "workflow": workflow,
        "task": await serialize_task_with_stats_func(db, task),
        "scheduler": scheduler,
    }


def _limit_per_repository(raw_payload: dict[str, Any], workflow: dict[str, Any]) -> int:
    return max(
        1,
        min(int(raw_payload.get("limit_per_repository") or workflow.get("limit_per_repository") or 30), 100),
    )


async def _schedule_fields(raw_payload: dict[str, Any], workflow: dict[str, Any]) -> tuple[str, str, str]:
    task_name = str(raw_payload.get("task_name") or f"Trace Sync: {workflow['name']}").strip()
    if not task_name:
        raise ValueError("Task name is required")
    task_description = str(
        raw_payload.get("task_description")
        or workflow.get("description")
        or f"Scheduled trace sync for workflow '{workflow['name']}'."
    ).strip()
    cron_expression = str(raw_payload.get("cron_expression") or "").strip()
    if not cron_expression:
        raise ValueError("cron_expression is required")
    # Refuse an unschedulable cron (typed 422) before the task and steps are committed, with the
    # exact string create_scheduler validates again below. Lazy: the scheduler package imports the agent
    # engine, which imports this module.
    from ...scheduler.dispatch.cron_schedule import require_schedulable_cron

    await require_schedulable_cron(cron_expression)
    return task_name, task_description, cron_expression


async def _add_sync_steps(
    db: AsyncSession,
    task: Task,
    workflow: dict[str, Any],
    *,
    project_id: str,
    workflow_id: str,
    limit_per_repository: int,
) -> None:
    step_fetch = TaskStep(
        task_id=task.id,
        position=1,
        name=f"Run {workflow['name']}",
        step_type="connector_fetch",
        connector="system",
        connector_action="run_design_trace_sync_workflow",
        instructions="Execute the configured design trace sync workflow and collect created links or suggestions.",
        is_enabled=True,
    )
    step_fetch.connector_params_json = json.dumps(
        {
            "project_id": project_id,
            "workflow_id": workflow_id,
            "limit_per_repository": limit_per_repository,
        }
    )
    step_output = TaskStep(
        task_id=task.id,
        position=2,
        name="Summarize trace sync result",
        step_type="output",
        instructions=(
            "Summarize the workflow result, including candidate count, created count, repositories scanned, "
            "and whether the workflow was in suggest or auto-link mode."
        ),
        is_enabled=True,
    )
    db.add(step_fetch)
    db.add(step_output)
    await db.commit()
    await db.refresh(task)
