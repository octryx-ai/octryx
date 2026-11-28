from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_tool_surface_contract import snapshot_tool_surface_entry

from ...models import AgentDefinition, AgentStep, Skill, Task, TaskDependency
from ...services.agent_reply_contract import snapshot_reply_contract_entry
from ...services.skill_catalog.portable import portable_skill
from ...time_utils import utc_now_aware


async def serialize_skill_content(db: AsyncSession, skill: Skill) -> dict[str, Any] | None:
    entity = await portable_skill(db, skill)
    if entity is None:
        return None
    return {
        "format_version": 1,
        "package_type": "skill",
        "entity": entity,
        "source": {"entity_id": skill.id, "exported_at": utc_now_aware().isoformat()},
    }


def serialize_agent_step(step: AgentStep) -> dict[str, Any]:
    return {
        "position": int(step.position or 1),
        "name": step.name,
        "step_type": step.step_type,
        "instructions": step.instructions or "",
        "success_criteria": step.success_criteria or "",
        "allowed_tools": list(step.allowed_tools or []),
        "step_config": step.step_config or {},
        "is_enabled": bool(step.is_enabled),
    }


def serialize_agent_content(agent: AgentDefinition) -> dict[str, Any]:
    entity = {
        "name": agent.name,
        "description": agent.description or "",
        "goal": agent.goal or "",
        "agent_type": agent.agent_type or "diagnosis",
        "thinking_level": agent.thinking_level or "light",
        "branch_prefix": agent.branch_prefix or "codex",
        "system_prompt": agent.system_prompt or "",
        "output_prompt": agent.output_prompt or "",
        "skill_preferences": agent.skill_preferences,
        "require_self_review": bool(agent.require_self_review),
        **snapshot_tool_surface_entry(agent.tool_surface),
        **snapshot_reply_contract_entry(agent.reply_contract_json),
        "is_active": bool(agent.is_active),
        "steps": [serialize_agent_step(step) for step in agent.steps],
    }
    return {
        "format_version": 1,
        "package_type": "agent",
        "entity": entity,
        "source": {
            "entity_id": agent.id,
            "project_id": agent.project_id,
            "exported_at": utc_now_aware().isoformat(),
        },
    }


def serialize_task_step(step) -> dict[str, Any]:
    return {
        "position": int(step.position or 1),
        "name": step.name,
        "step_type": step.step_type or "analysis",
        "connector": step.connector,
        "connector_action": step.connector_action,
        "connector_params": step.connector_params or {},
        "instructions": step.instructions or "",
        "runtime_selector": step.runtime_selector or {},
        "context_fields": list(step.context_fields or []),
        "allowed_tools": list(step.allowed_tools or []),
        "spawn_strategy": step.spawn_strategy or "per_item",
        "spawn_count": step.spawn_count,
        "max_fix_attempts": int(step.max_fix_attempts or 2),
        "condition_expr": step.condition_expr or "",
        "condition_true_step": step.condition_true_step,
        "condition_false_step": step.condition_false_step,
        "agent_timeout_seconds": int(step.agent_timeout_seconds or 300),
        "is_enabled": bool(step.is_enabled),
    }


async def serialize_task_content(db: AsyncSession, task: Task) -> dict[str, Any]:
    dependencies = (
        await db.execute(
            select(TaskDependency, Task)
            .join(Task, Task.id == TaskDependency.depends_on_task_id)
            .where(TaskDependency.task_id == task.id)
        )
    ).all()
    dependency_rows = []
    for dependency, upstream in dependencies:
        dependency_rows.append(
            {
                "depends_on_task_name": upstream.name,
                "condition": dependency.condition or "success",
            }
        )
    entity = {
        "name": task.name,
        "description": task.description or "",
        "task_type": task.task_type or "agent_run",
        "agent_type": task.agent_type or "diagnosis",
        "schedule": task.schedule,
        "config": task.config or {},
        "max_concurrent_agents": int(task.max_concurrent_agents or 3),
        "default_runtime_selector": task.default_runtime_selector or {},
        "is_active": bool(task.is_active),
        "dispatch_binding": task.dispatch_binding,
        "steps": [serialize_task_step(step) for step in task.steps],
        "dependencies": dependency_rows,
    }
    return {
        "format_version": 1,
        "package_type": "task",
        "entity": entity,
        "source": {
            "entity_id": task.id,
            "project_id": task.project_id,
            "exported_at": utc_now_aware().isoformat(),
        },
    }
