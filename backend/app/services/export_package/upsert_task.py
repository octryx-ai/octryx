"""Upsert an imported task with its steps and dependencies."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import Task, TaskDependency, TaskStep, User
from ...services.admin.task._dispatch_binding import require_binding_value, require_bound_state
from ...services.entity_version import snapshot_task_step
from ...services.task_schedule_authoring import require_task_schedule


def _apply_task_fields(task: Task, entity: dict[str, Any], *, name: str, target_project_id: str | None) -> None:
    task.name = name
    task.project_id = target_project_id
    task.description = str(entity.get("description") or "")
    task.task_type = str(entity.get("task_type") or "agent_run")
    task.agent_type = str(entity.get("agent_type") or "diagnosis")
    task.schedule = entity.get("schedule")
    task.config = entity.get("config") if isinstance(entity.get("config"), dict) else {}
    task.max_concurrent_agents = int(entity.get("max_concurrent_agents") or 3)
    task.default_runtime_selector = (
        entity.get("default_runtime_selector") if isinstance(entity.get("default_runtime_selector"), dict) else {}
    )
    task.is_active = bool(entity.get("is_active", True))
    task.dispatch_binding = entity["dispatch_binding"]


def _task_step(task: Task, step_payload: dict[str, Any]) -> TaskStep:
    step = TaskStep(
        id=str(uuid.uuid4()),
        task_id=task.id,
        position=int(step_payload.get("position") or 1),
        name=str(step_payload.get("name") or "Step"),
        step_type=str(step_payload.get("step_type") or "analysis"),
        connector=step_payload.get("connector"),
        connector_action=step_payload.get("connector_action"),
        instructions=str(step_payload.get("instructions") or ""),
        spawn_strategy=str(step_payload.get("spawn_strategy") or "per_item"),
        spawn_count=step_payload.get("spawn_count"),
        max_fix_attempts=int(step_payload.get("max_fix_attempts") or 2),
        condition_expr=str(step_payload.get("condition_expr") or "") or None,
        condition_true_step=step_payload.get("condition_true_step"),
        condition_false_step=step_payload.get("condition_false_step"),
        agent_timeout_seconds=int(step_payload.get("agent_timeout_seconds") or 300),
        is_enabled=bool(step_payload.get("is_enabled", True)),
    )
    step.connector_params_json = json.dumps(step_payload.get("connector_params") or {})
    step.runtime_selector_json = json.dumps(step_payload.get("runtime_selector") or {})
    step.context_fields_json = json.dumps(step_payload.get("context_fields") or [])
    step.allowed_tools_json = json.dumps(step_payload.get("allowed_tools") or [])
    return step


async def _add_task_steps(
    db: AsyncSession, task: Task, entity: dict[str, Any], *, current_user: User, existing: Task | None
) -> None:
    for step_payload in entity.get("steps") or []:
        step = _task_step(task, step_payload)
        db.add(step)
        await db.flush()
        await snapshot_task_step(db, step, changed_by=current_user.id, operation="update" if existing else "create")


async def _add_task_dependencies(
    db: AsyncSession, task: Task, entity: dict[str, Any], *, target_project_id: str | None, warnings: list[str]
) -> None:
    for dependency_payload in entity.get("dependencies") or []:
        depends_on_name = str(dependency_payload.get("depends_on_task_name") or "").strip()
        if not depends_on_name:
            continue
        upstream = (
            await db.execute(select(Task).where(Task.project_id == target_project_id, Task.name == depends_on_name))
        ).scalar_one_or_none()
        if upstream is None:
            warnings.append(f"Skipped dependency '{depends_on_name}' because it does not exist in target project")
            continue
        db.add(
            TaskDependency(
                id=str(uuid.uuid4()),
                task_id=task.id,
                depends_on_task_id=upstream.id,
                condition=str(dependency_payload.get("condition") or "success"),
            )
        )


async def upsert_task_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
    target_project_id: str | None,
) -> tuple[Task, list[str]]:
    warnings: list[str] = []
    name = str(name_override or entity.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Task package missing name")
    stmt = select(Task).options(selectinload(Task.steps)).where(Task.name == name, Task.project_id == target_project_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing and not overwrite_existing:
        raise HTTPException(status_code=409, detail=f"Task '{name}' already exists in target project")
    # Checked before any change, so a refused schedule or binding never half-updates an existing task.
    await require_task_schedule(entity.get("schedule"))
    await require_bound_state(
        db, binding=require_binding_value(entity.get("dispatch_binding")),
        task_type=str(entity.get("task_type") or "agent_run"),
        config=entity.get("config") if isinstance(entity.get("config"), dict) else {},
        owner_id=existing.owner_id if existing else current_user.id, project_id=target_project_id,
        has_enabled_steps=any(bool(step.get("is_enabled", True)) for step in entity.get("steps") or []),
    )
    task = existing or Task(id=str(uuid.uuid4()), owner_id=current_user.id, project_id=target_project_id)
    _apply_task_fields(task, entity, name=name, target_project_id=target_project_id)
    db.add(task)
    await db.flush()
    if existing:
        # Imported here: the step deletes are an Agent Definition writer match for the inventory scan, so they stay
        # in the registered ``upsert`` module, which itself imports this one.
        from .upsert import _drop_task_children

        await _drop_task_children(db, task, existing)
    await _add_task_steps(db, task, entity, current_user=current_user, existing=existing)
    await _add_task_dependencies(db, task, entity, target_project_id=target_project_id, warnings=warnings)
    return task, warnings
