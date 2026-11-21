"""Service helpers for admin-panel agent builder flows.

Every function here that creates or changes agent rows stays in this module, because it
is the registered panel writer of the agent aggregate. Request checks and read queries
live in the ``_admin_agent_*`` modules beside it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_tool_surface_contract import step_row_view

from ....models import AgentDefinition, AgentStep
from ...agent_definition_authoring import governs_agent_definition_write
from ...agent_definition_writers import AgentDefinitionWriter
from ...agent_setup_fields import capability_ceiling_from, default_workflow_key_from, execution_mode_from
from ...agent_visibility import editable_agent_clause
from ...entity_version import snapshot_agent_definition
from ...skill_assignment_service import normalize_agent_skill_preferences
from ._admin_agent_inputs import (
    AgentUpdateInputs,
    _refuse_tool_surface_conflict,
    agent_update_inputs,
    editable_agent,
    editable_agent_with_steps,
    editable_step_with_surface,
    new_agent_fields,
    reloaded_agent,
    step_request_view,
)


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def create_agent(
    db: AsyncSession,
    *,
    user_id: str,
    payload: dict[str, Any],
    thinking_levels: list[str],
    serialize_agent_definition: Callable[[AgentDefinition], dict[str, Any]],
) -> dict[str, Any]:
    agent = AgentDefinition(
        **await new_agent_fields(db, user_id=user_id, payload=payload, thinking_levels=thinking_levels)
    )
    agent.skill_preferences = normalize_agent_skill_preferences(
        payload.get("skill_preferences") or payload.get("skillPreferences")
    )
    db.add(agent)
    await db.flush()
    await snapshot_agent_definition(db, agent, changed_by=user_id, operation="create")
    await db.commit()
    refreshed = await reloaded_agent(db, agent.id)
    return serialize_agent_definition(refreshed or agent)


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def update_agent(
    db: AsyncSession,
    *,
    user_id: str,
    agent_id: str,
    payload: dict[str, Any],
    thinking_levels: list[str],
    serialize_agent_definition: Callable[[AgentDefinition], dict[str, Any]],
) -> dict[str, Any]:
    agent = await editable_agent_with_steps(db, user_id=user_id, agent_id=agent_id)
    inputs = await agent_update_inputs(db, agent, payload, thinking_levels)
    _apply_agent_update(agent, payload, inputs)
    await db.flush()
    await snapshot_agent_definition(db, agent, changed_by=user_id, operation="update")
    await db.commit()
    refreshed = await reloaded_agent(db, agent.id)
    return serialize_agent_definition(refreshed or agent)


def _apply_agent_update(agent: AgentDefinition, payload: dict[str, Any], inputs: AgentUpdateInputs) -> None:
    agent.name = inputs.name
    agent.description = str(payload.get("description") or "").strip()
    agent.goal = str(payload.get("goal") or "").strip()
    agent.group_id = str(payload.get("group_id") or "").strip() or None
    agent.runtime_target_id = str(payload.get("runtime_target_id") or "").strip() or None
    agent.agent_type = inputs.agent_type
    agent.thinking_level = inputs.thinking_level
    agent.branch_prefix = inputs.branch_prefix
    agent.require_self_review = bool(
        payload.get("require_self_review", payload.get("requireSelfReview", agent.require_self_review))
    )
    agent.tool_surface = inputs.tool_surface
    agent.reply_contract_json = inputs.reply_contract_json
    agent.capability_ceiling = capability_ceiling_from(payload, current=agent.capability_ceiling)
    agent.default_workflow_key = default_workflow_key_from(payload, current=agent.default_workflow_key)
    agent.execution_mode = execution_mode_from(payload, current=agent.execution_mode)
    agent.system_prompt = str(payload.get("system_prompt") or "").strip()
    agent.output_prompt = str(payload.get("output_prompt") or "").strip()
    if "skill_preferences" in payload or "skillPreferences" in payload:
        agent.skill_preferences = normalize_agent_skill_preferences(
            payload.get("skill_preferences") or payload.get("skillPreferences")
        )
    agent.is_active = bool(payload.get("is_active", True))


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def delete_agent(db: AsyncSession, *, user_id: str, agent_id: str) -> dict[str, Any]:
    agent = await editable_agent(db, user_id=user_id, agent_id=agent_id)
    if agent.builtin_key:
        raise HTTPException(status_code=409, detail="A built-in agent cannot be deleted")
    await snapshot_agent_definition(db, agent, changed_by=user_id, operation="delete")
    await db.delete(agent)
    await db.commit()
    return {"status": "deleted"}


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def create_agent_step(
    db: AsyncSession,
    *,
    user_id: str,
    agent_id: str,
    payload: dict[str, Any],
    serialize_agent_step: Callable[[AgentStep], dict[str, Any]],
) -> dict[str, Any]:
    agent = await editable_agent_with_steps(db, user_id=user_id, agent_id=agent_id)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Step name is required")
    max_position = (
        await db.execute(select(func.max(AgentStep.position)).where(AgentStep.agent_id == agent.id))
    ).scalar_one()
    step = AgentStep(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        position=int(max_position or 0) + 1,
        name=name,
        step_type=str(payload.get("step_type") or "analysis").strip() or "analysis",
        instructions=str(payload.get("instructions") or "").strip(),
        success_criteria=str(payload.get("success_criteria") or "").strip(),
        allowed_tools=[str(item).strip() for item in (payload.get("allowed_tools") or []) if str(item).strip()],
        step_config=dict(payload.get("step_config") or {}),
        is_enabled=bool(payload.get("is_enabled", True)),
    )
    _refuse_tool_surface_conflict(agent.tool_surface, [step_row_view(step)])
    db.add(step)
    await db.commit()
    return serialize_agent_step(step)


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def update_agent_step(
    db: AsyncSession,
    *,
    user_id: str,
    agent_id: str,
    step_id: str,
    payload: dict[str, Any],
    serialize_agent_step: Callable[[AgentStep], dict[str, Any]],
) -> dict[str, Any]:
    step, agent_tool_surface = await editable_step_with_surface(
        db, user_id=user_id, agent_id=agent_id, step_id=step_id
    )
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Step name is required")
    _refuse_tool_surface_conflict(agent_tool_surface, [step_request_view(name, payload)])
    step.name = name
    step.step_type = str(payload.get("step_type") or "analysis").strip() or "analysis"
    step.instructions = str(payload.get("instructions") or "").strip()
    step.success_criteria = str(payload.get("success_criteria") or "").strip()
    step.allowed_tools = [str(item).strip() for item in (payload.get("allowed_tools") or []) if str(item).strip()]
    step.step_config = dict(payload.get("step_config") or {})
    step.is_enabled = bool(payload.get("is_enabled", True))
    await db.commit()
    return serialize_agent_step(step)


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def delete_agent_step(db: AsyncSession, *, user_id: str, agent_id: str, step_id: str) -> dict[str, Any]:
    step = (
        await db.execute(
            select(AgentStep)
            .join(AgentDefinition, AgentDefinition.id == AgentStep.agent_id)
            .where(
                AgentStep.id == step_id, AgentStep.agent_id == agent_id, await editable_agent_clause(db, user_id)
            )
        )
    ).scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    await db.delete(step)
    await db.flush()
    remaining_steps = (
        (await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id).order_by(AgentStep.position.asc())))
        .scalars()
        .all()
    )
    for index, current_step in enumerate(remaining_steps, start=1):
        current_step.position = index
    await db.commit()
    return {"status": "deleted"}


@governs_agent_definition_write(
    AgentDefinitionWriter.PANEL_AGENT_CRUD, actor_param="user_id"
)
async def reorder_agent_steps(
    db: AsyncSession,
    *,
    user_id: str,
    agent_id: str,
    order: list[str],
    serialize_agent_step: Callable[[AgentStep], dict[str, Any]],
) -> list[dict[str, Any]]:
    await editable_agent(db, user_id=user_id, agent_id=agent_id)
    result = await db.execute(select(AgentStep).where(AgentStep.agent_id == agent_id))
    steps_map = {step.id: step for step in result.scalars().all()}
    for pos, step_id in enumerate(order, start=1):
        if step_id in steps_map:
            steps_map[step_id].position = pos
    await db.commit()
    result2 = await db.execute(
        select(AgentStep).where(AgentStep.agent_id == agent_id).order_by(AgentStep.position.asc())
    )
    return [serialize_agent_step(step) for step in result2.scalars().all()]

