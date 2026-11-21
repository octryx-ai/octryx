"""Task step operations for admin task service."""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Task, TaskStep
from ...entity_version import snapshot_task_step
from ...run_capability.schedule_capability import require_valid_schedule_capability
from ._admin_task_serialization import serialize_task_step
from ._dispatch_binding import require_step_allowed


async def list_task_steps(db: AsyncSession, *, task_id: str) -> list[dict[str, Any]]:
    result = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.position))
    return [serialize_task_step(step) for step in result.scalars().all()]


async def create_task_step(db: AsyncSession, *, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    # An agent-bound Action never gains an enabled step.
    require_step_allowed(binding=task.dispatch_binding, enabled=bool(payload.get("is_enabled", True)))

    max_pos = (await db.execute(select(func.max(TaskStep.position)).where(TaskStep.task_id == task_id))).scalar() or 0
    step = TaskStep(
        task_id=task_id,
        position=max_pos + 1,
        name=str(payload.get("name") or "Step"),
        step_type=str(payload.get("step_type") or "analysis"),
        connector=payload.get("connector"),
        connector_action=payload.get("connector_action"),
        connector_params_json=json.dumps(payload.get("connector_params") or {}),
        instructions=str(payload.get("instructions") or ""),
        runtime_selector_json=json.dumps(payload.get("runtime_selector") or {}),
        context_fields_json=json.dumps(payload.get("context_fields") or []),
        allowed_tools_json=json.dumps(payload.get("allowed_tools") or []),
        spawn_strategy=str(payload.get("spawn_strategy") or "per_item"),
        spawn_count=payload.get("spawn_count"),
        max_fix_attempts=int(payload.get("max_fix_attempts") or 2),
        condition_expr=payload.get("condition_expr"),
        condition_true_step=payload.get("condition_true_step"),
        condition_false_step=payload.get("condition_false_step"),
        agent_timeout_seconds=int(payload.get("agent_timeout_seconds") or 300),
        is_enabled=bool(payload.get("is_enabled", True)),
    )
    require_valid_schedule_capability(task.config, [step])
    db.add(step)
    await db.flush()
    await snapshot_task_step(db, step, changed_by=task.owner_id, operation="create")
    await db.commit()
    await db.refresh(step)
    return serialize_task_step(step)


async def update_task_step(db: AsyncSession, *, task_id: str, step_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    step = (
        await db.execute(select(TaskStep).where(TaskStep.id == step_id, TaskStep.task_id == task_id))
    ).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    # Checked before any field changes; an agent-bound Action never gains an enabled step.
    binding = (await db.execute(select(Task.dispatch_binding).where(Task.id == task_id))).scalar_one_or_none()
    require_step_allowed(binding=binding, enabled=bool(payload["is_enabled"] if "is_enabled" in payload else step.is_enabled))

    for field in [
        "name",
        "step_type",
        "connector",
        "connector_action",
        "instructions",
        "spawn_strategy",
        "spawn_count",
        "max_fix_attempts",
        "condition_expr",
        "condition_true_step",
        "condition_false_step",
        "agent_timeout_seconds",
        "is_enabled",
        "position",
    ]:
        if field in payload:
            setattr(step, field, payload[field])
    if "runtime_selector" in payload:
        step.runtime_selector_json = json.dumps(payload["runtime_selector"] or {})
    if "context_fields" in payload:
        step.context_fields_json = json.dumps(payload["context_fields"] or [])
    if "allowed_tools" in payload:
        step.allowed_tools_json = json.dumps(payload["allowed_tools"] or [])
    if "connector_params" in payload:
        step.connector_params_json = json.dumps(payload["connector_params"] or {})
    task_config = (await db.execute(select(Task.config).where(Task.id == task_id))).scalar_one_or_none()
    require_valid_schedule_capability(task_config, [step])
    await db.flush()
    owner_id = (await db.execute(select(Task.owner_id).where(Task.id == task_id))).scalar_one_or_none()
    await snapshot_task_step(db, step, changed_by=owner_id, operation="update")
    await db.commit()
    await db.refresh(step)
    return serialize_task_step(step)


async def delete_task_step(db: AsyncSession, *, task_id: str, step_id: str) -> dict[str, Any]:
    step = (
        await db.execute(select(TaskStep).where(TaskStep.id == step_id, TaskStep.task_id == task_id))
    ).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    owner_id = (await db.execute(select(Task.owner_id).where(Task.id == task_id))).scalar_one_or_none()
    await snapshot_task_step(db, step, changed_by=owner_id, operation="delete")
    await db.delete(step)
    await db.commit()
    return {"status": "deleted"}


async def reorder_task_steps(db: AsyncSession, *, task_id: str, order: list[str]) -> list[dict[str, Any]]:
    result = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id))
    steps_map = {step.id: step for step in result.scalars().all()}
    for pos, step_id in enumerate(order, start=1):
        if step_id in steps_map:
            steps_map[step_id].position = pos
    await db.commit()
    updated = await db.execute(select(TaskStep).where(TaskStep.task_id == task_id).order_by(TaskStep.position))
    return [serialize_task_step(step) for step in updated.scalars().all()]
