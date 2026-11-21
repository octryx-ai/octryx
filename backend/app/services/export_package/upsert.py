"""Upsert an imported skill or agent definition; task imports live in ``upsert_task``."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.agent_reply_contract_schema import REPLY_CONTRACT_FIELD, ReplyContractError
from app.services.agent_tool_surface_contract import (
    TOOL_SURFACE_FIELD,
    ToolSurfaceConflictError,
    declared_tool_surface,
    ensure_no_step_conflict,
)

from ...models import AgentDefinition, AgentStep, Skill, Task, TaskDependency, User
from ...services.agent_definition_authoring import governs_agent_definition_write
from ...services.agent_definition_writers import AgentDefinitionWriter
from ...services.agent_reply_contract import declared_reply_contract, reply_contract_column
from ...services.entity_version import snapshot_agent_definition
from ...services.skill_assignment_service import normalize_agent_skill_preferences
from ...services.skill_catalog.errors import SkillCatalogError
from ...services.skill_catalog.portable import import_portable_skill


def _imported_reply_contract(entity: dict[str, Any]) -> str | None:
    """A package without the key is free text; a present ``null`` or invalid contract refuses the import."""
    try:
        declared = declared_reply_contract(entity, REPLY_CONTRACT_FIELD)
        return None if declared is None else reply_contract_column(declared)
    except ReplyContractError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _imported_tool_surface(entity: dict[str, Any]) -> str:
    """A package without the key is ``governed``; a present ``null``/empty/unknown value refuses the import."""
    try:
        return declared_tool_surface(entity, TOOL_SURFACE_FIELD)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def upsert_skill_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
) -> tuple[Skill, list[str]]:
    warnings: list[str] = []
    name = str(name_override or entity.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Skill package missing name")
    # An imported skill lands as a catalog draft; publishing is the four-eyes catalog lifecycle.
    try:
        skill, _created = await import_portable_skill(
            db, entity, name=name, overwrite_existing=overwrite_existing, actor_id=current_user.id
        )
    except SkillCatalogError as error:
        raise HTTPException(status_code=error.status, detail=error.as_detail()) from None
    warnings.append(f"Skill '{name}' was imported as a catalog draft; publish it after review.")
    await db.flush()
    return skill, warnings


def _apply_agent_fields(
    agent: AgentDefinition,
    entity: dict[str, Any],
    *,
    name: str,
    reply_contract_json: str | None,
) -> None:
    agent.name = name
    agent.description = str(entity.get("description") or "")
    agent.goal = str(entity.get("goal") or "")
    agent.agent_type = str(entity.get("agent_type") or "diagnosis")
    agent.thinking_level = str(entity.get("thinking_level") or "light")
    agent.branch_prefix = str(entity.get("branch_prefix") or "codex")
    agent.system_prompt = str(entity.get("system_prompt") or "")
    agent.output_prompt = str(entity.get("output_prompt") or "")
    agent.skill_preferences = normalize_agent_skill_preferences(entity.get("skill_preferences"))
    agent.require_self_review = bool(entity.get("require_self_review"))
    agent.tool_surface = _imported_tool_surface(entity)
    agent.reply_contract_json = reply_contract_json
    agent.is_active = bool(entity.get("is_active", True))
    agent.runtime_target_id = None


async def _replace_agent_steps(db: AsyncSession, agent: AgentDefinition, existing: Any, entity: dict[str, Any]) -> None:
    """Drop an existing definition's steps and add the package's steps."""
    if existing:
        for step in list(existing.steps):
            await db.delete(step)
        await db.flush()
    for step_payload in entity.get("steps") or []:
        step = AgentStep(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            position=int(step_payload.get("position") or 1),
            name=str(step_payload.get("name") or "Step"),
            step_type=str(step_payload.get("step_type") or "analysis"),
            instructions=str(step_payload.get("instructions") or ""),
            success_criteria=str(step_payload.get("success_criteria") or ""),
            is_enabled=bool(step_payload.get("is_enabled", True)),
        )
        step.allowed_tools = [str(item) for item in step_payload.get("allowed_tools") or []]
        step.step_config = step_payload.get("step_config") if isinstance(step_payload.get("step_config"), dict) else {}
        db.add(step)
    await db.flush()


@governs_agent_definition_write(
    AgentDefinitionWriter.PACKAGE_IMPORT, actor_param="current_user"
)


async def upsert_agent_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
) -> tuple[AgentDefinition, list[str]]:
    warnings: list[str] = []
    name = str(name_override or entity.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Agent package missing name")
    stmt = (
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps))
        .where(
            AgentDefinition.name == name,
            AgentDefinition.project_id.is_(None),
        )
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing and not overwrite_existing:
        raise HTTPException(status_code=409, detail=f"Agent '{name}' already exists")
    # A package that combines No tools with tool-using steps is refused before anything is written.
    try:
        ensure_no_step_conflict(_imported_tool_surface(entity), entity.get("steps") or [])
    except ToolSurfaceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    reply_contract_json = _imported_reply_contract(entity)
    # Agents are Global: an import never creates a Workspace-owned agent.
    agent = existing or AgentDefinition(id=str(uuid.uuid4()), owner_id=current_user.id)
    _apply_agent_fields(agent, entity, name=name, reply_contract_json=reply_contract_json)
    db.add(agent)
    await db.flush()
    await _replace_agent_steps(db, agent, existing, entity)
    await snapshot_agent_definition(
        db,
        agent,
        changed_by=current_user.id,
        operation="update" if existing else "create",
    )
    return agent, warnings


async def _drop_task_children(db: AsyncSession, task: Task, existing: Task) -> None:
    """An overwritten task loses its old dependencies and steps before the package's are added."""
    for dependency in (
        (await db.execute(select(TaskDependency).where(TaskDependency.task_id == task.id))).scalars().all()
    ):
        await db.delete(dependency)
    for step in list(existing.steps):
        await db.delete(step)
    await db.flush()
