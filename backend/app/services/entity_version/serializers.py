"""Snapshot serializers of the versioned entities (agent definitions, task steps)."""

from __future__ import annotations

from typing import Any

from ...models import AgentDefinition, TaskStep


def _serialize_agent_definition(agent: AgentDefinition) -> dict[str, Any]:
    return {
        "id": agent.id,
        "owner_id": agent.owner_id,
        "project_id": agent.project_id,
        "runtime_target_id": agent.runtime_target_id,
        "name": agent.name,
        "description": agent.description,
        "goal": agent.goal,
        "agent_type": agent.agent_type,
        "thinking_level": agent.thinking_level,
        "branch_prefix": agent.branch_prefix,
        "system_prompt": agent.system_prompt,
        "output_prompt": agent.output_prompt,
        "skill_preferences": agent.skill_preferences,
        "require_self_review": agent.require_self_review,
        "tool_surface": agent.tool_surface,
        "is_active": agent.is_active,
    }


def _serialize_task_step(step: TaskStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "task_id": step.task_id,
        "position": step.position,
        "name": step.name,
        "step_type": step.step_type,
        "connector": step.connector,
        "connector_action": step.connector_action,
        "connector_params": step.connector_params,
        "instructions": step.instructions,
        "runtime_selector": step.runtime_selector,
        "context_fields": step.context_fields,
        "allowed_tools": step.allowed_tools,
        "spawn_strategy": step.spawn_strategy,
        "spawn_count": step.spawn_count,
        "max_fix_attempts": step.max_fix_attempts,
        "condition_expr": step.condition_expr,
        "condition_true_step": step.condition_true_step,
        "condition_false_step": step.condition_false_step,
        "agent_timeout_seconds": step.agent_timeout_seconds,
        "is_enabled": step.is_enabled,
    }
