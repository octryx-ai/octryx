"""Serialization helpers for admin task service payloads."""

from __future__ import annotations

from typing import Any

from ....models import Task, TaskDependency, TaskRun, TaskStep


def serialize_task(
    task: Task,
    *,
    run_count: int,
    running_count: int,
    queued_count: int,
    last_run: TaskRun | None,
    step_count: int,
    dependency_count: int,
    dependent_count: int,
    next_queue_priority: int | None,
) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "description": task.description or "",
        # Additive: the Action's Workspace, for an honest guided edit context.
        "project_id": task.project_id,
        # Additive: the Action's explicit dispatch binding (null = worker dispatch).
        "dispatch_binding": task.dispatch_binding,
        "task_type": task.task_type,
        "agent_type": task.agent_type or "diagnosis",
        "schedule": task.schedule,
        "is_active": task.is_active,
        "config": task.config or {},
        "max_concurrent_agents": task.max_concurrent_agents or 3,
        "default_runtime_selector": task.default_runtime_selector,
        "owner_id": task.owner_id,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "run_count": run_count,
        "running_count": running_count,
        "queued_count": queued_count,
        "last_run_status": last_run.status if last_run else None,
        "last_run_at": last_run.started_at.isoformat() if last_run and last_run.started_at else None,
        "step_count": step_count,
        "dependency_count": dependency_count,
        "dependent_count": dependent_count,
        "next_queue_priority": next_queue_priority,
    }


def serialize_task_step(step: TaskStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "task_id": step.task_id,
        "position": step.position,
        "name": step.name,
        "step_type": step.step_type,
        "connector": step.connector,
        "connector_action": step.connector_action,
        "connector_params": step.connector_params,
        "instructions": step.instructions or "",
        "runtime_selector": step.runtime_selector,
        "context_fields": step.context_fields,
        "allowed_tools": step.allowed_tools,
        "spawn_strategy": step.spawn_strategy or "per_item",
        "spawn_count": step.spawn_count,
        "max_fix_attempts": step.max_fix_attempts or 2,
        "condition_expr": step.condition_expr or "",
        "condition_true_step": step.condition_true_step,
        "condition_false_step": step.condition_false_step,
        "agent_timeout_seconds": step.agent_timeout_seconds or 300,
        "is_enabled": step.is_enabled,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def serialize_task_dependency(entry: TaskDependency, *, task_lookup: dict[str, Task]) -> dict[str, Any]:
    dependency_task = task_lookup.get(entry.depends_on_task_id)
    source_task = task_lookup.get(entry.task_id)
    return {
        "id": entry.id,
        "task_id": entry.task_id,
        "depends_on_task_id": entry.depends_on_task_id,
        "condition": entry.condition,
        "task_name": source_task.name if source_task else entry.task_id,
        "depends_on_task_name": dependency_task.name if dependency_task else entry.depends_on_task_id,
    }
