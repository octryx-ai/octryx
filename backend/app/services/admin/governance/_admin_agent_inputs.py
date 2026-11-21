"""Request checks, field values and row lookups for the admin-panel agent builder.

Nothing here constructs or changes an agent row: the registered writer
:mod:`app.services.admin.governance.admin_agent_service` does that with the values
prepared here, so the writer inventory keeps naming the one module that writes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.agent_reply_contract_schema import ReplyContractError
from app.services.agent_tool_surface_contract import (
    DEFAULT_TOOL_SURFACE,
    ToolSurfaceConflictError,
    declared_tool_surface,
    ensure_no_step_conflict,
    normalize_tool_surface,
    step_row_view,
)

from ....models import AgentDefinition, AgentStep
from ...agent_mode import require_agent_mode
from ...agent_reply_contract import reply_contract_column_for_write
from ...agent_setup_fields import capability_ceiling_from, default_workflow_key_from, execution_mode_from
from ...agent_visibility import editable_agent_clause

# The mode an agent row records, derived from its ceiling.
_AGENT_TYPE_FOR_CEILING = {"read_only": "diagnosis", "change": "change", "deliver": "change"}


def _tool_surface_from_payload(payload: dict[str, Any], *, default: str | None) -> str:
    """The requested tool surface; an absent key keeps *default* (``governed`` on create).

    The request schema already refuses unknown values; this re-checks for direct callers, so a
    present ``null`` or ``""`` is refused instead of falling back.
    """
    if "tool_surface" not in payload:
        if default is None:
            return DEFAULT_TOOL_SURFACE
        try:
            # A stored invalid value is never kept or widened by a save that does not choose one.
            return normalize_tool_surface(default)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="The stored tool setting is not valid; choose policy-governed tools or No tools (text only).",
            ) from exc
    try:
        return declared_tool_surface(payload, "tool_surface")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _reply_contract_from_payload(payload: dict[str, Any], *, stored: str | None) -> str | None:
    """The reply contract column: an absent key keeps *stored*; ``None`` from the route is absent."""
    present = {"reply_contract": payload["reply_contract"]} if payload.get("reply_contract") is not None else {}
    try:
        return reply_contract_column_for_write(present, stored=stored)
    except ReplyContractError as exc:
        raise HTTPException(
            status_code=422, detail={"message": str(exc), "code": exc.code, "field": "reply_contract"}
        ) from None


def _refuse_tool_surface_conflict(tool_surface: str | None, steps: list[dict[str, Any]]) -> None:
    """No tools (text only) never coexists with steps that use tools; nothing is changed silently."""
    try:
        ensure_no_step_conflict(tool_surface or "", steps)
    except ToolSurfaceConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc





async def new_agent_fields(
    db: AsyncSession, *, user_id: str, payload: dict[str, Any], thinking_levels: list[str]
) -> dict[str, Any]:
    """Checked constructor values of an agent created from a panel request."""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Agent name is required")

    # Fail closed on an unknown mode instead of storing a silently remapped one
    # the accepted key set is the one publication accepts.
    ceiling = capability_ceiling_from(payload, current=None)
    resolved_mode = await require_agent_mode(db, str(payload.get("agent_type") or _AGENT_TYPE_FOR_CEILING[ceiling]))
    thinking_level = str(payload.get("thinking_level") or "light").strip()
    if thinking_level not in thinking_levels:
        thinking_level = "light"
    branch_prefix = str(payload.get("branch_prefix") or "octryx").strip().strip("/") or "octryx"
    return {
        "id": str(uuid.uuid4()),
        "owner_id": user_id,
        "name": name,
        "description": str(payload.get("description") or "").strip(),
        "goal": str(payload.get("goal") or "").strip(),
        "group_id": str(payload.get("group_id") or "").strip() or None,
        "runtime_target_id": str(payload.get("runtime_target_id") or "").strip() or None,
        "agent_type": resolved_mode.key,
        "thinking_level": thinking_level,
        "branch_prefix": branch_prefix,
        "require_self_review": bool(payload.get("require_self_review", payload.get("requireSelfReview", False))),
        "tool_surface": _tool_surface_from_payload(payload, default=None),
        "reply_contract_json": _reply_contract_from_payload(payload, stored=None),
        "capability_ceiling": ceiling,
        "default_workflow_key": default_workflow_key_from(payload, current=None),
        "execution_mode": execution_mode_from(payload, current=None),
        "system_prompt": str(payload.get("system_prompt") or "").strip(),
        "output_prompt": str(payload.get("output_prompt") or "").strip(),
        "is_active": bool(payload.get("is_active", True)),
    }


@dataclass(frozen=True, slots=True)
class AgentUpdateInputs:
    """Values of a panel update that are checked before any field of the agent changes."""

    name: str
    tool_surface: str
    reply_contract_json: str | None
    agent_type: str
    thinking_level: str
    branch_prefix: str


async def agent_update_inputs(
    db: AsyncSession, agent: AgentDefinition, payload: dict[str, Any], thinking_levels: list[str]
) -> AgentUpdateInputs:
    """Check an update request against *agent*; a refused save leaves the agent untouched."""
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Agent name is required")

    tool_surface = _tool_surface_from_payload(payload, default=agent.tool_surface)
    _refuse_tool_surface_conflict(tool_surface, [step_row_view(step) for step in agent.steps])
    reply_contract_json = _reply_contract_from_payload(payload, stored=agent.reply_contract_json)
    resolved_mode = await require_agent_mode(db, str(payload.get("agent_type") or agent.agent_type or "diagnosis"))
    thinking_level = str(payload.get("thinking_level") or agent.thinking_level or "light").strip()
    if thinking_level not in thinking_levels:
        thinking_level = "light"
    branch_prefix = (
        str(payload.get("branch_prefix") or agent.branch_prefix or "octryx").strip().strip("/")
        or "octryx"
    )
    return AgentUpdateInputs(
        name=name,
        tool_surface=tool_surface,
        reply_contract_json=reply_contract_json,
        agent_type=resolved_mode.key,
        thinking_level=thinking_level,
        branch_prefix=branch_prefix,
    )


async def editable_agent_with_steps(db: AsyncSession, *, user_id: str, agent_id: str) -> AgentDefinition:
    """The agent with its steps and group loaded, if *user_id* may edit it; 404 otherwise."""
    agent = (
        await db.execute(
            select(AgentDefinition)
            .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
            .where(AgentDefinition.id == agent_id, await editable_agent_clause(db, user_id))
        )
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def reloaded_agent(db: AsyncSession, agent_id: str) -> AgentDefinition | None:
    """The agent read back after a commit, with steps and group loaded for serialization."""
    return (
        await db.execute(
            select(AgentDefinition)
            .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
            .where(AgentDefinition.id == agent_id)
        )
    ).scalar_one_or_none()


async def editable_agent(db: AsyncSession, *, user_id: str, agent_id: str) -> AgentDefinition:
    """The agent row alone, if *user_id* may edit it; 404 otherwise."""
    agent = (
        await db.execute(
            select(AgentDefinition).where(AgentDefinition.id == agent_id, await editable_agent_clause(db, user_id))
        )
    ).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def editable_step_with_surface(
    db: AsyncSession, *, user_id: str, agent_id: str, step_id: str
) -> tuple[AgentStep, str | None]:
    """The step and its agent's tool surface, if *user_id* may edit the agent; 404 otherwise."""
    row = (
        await db.execute(
            select(AgentStep, AgentDefinition.tool_surface)
            .join(AgentDefinition, AgentDefinition.id == AgentStep.agent_id)
            .where(
                AgentStep.id == step_id, AgentStep.agent_id == agent_id, await editable_agent_clause(db, user_id)
            )
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Step not found")
    step, agent_tool_surface = row
    return step, agent_tool_surface


def step_request_view(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The tool-relevant view of a requested step, for the tool-surface conflict check."""
    return {
        "name": name,
        "is_enabled": bool(payload.get("is_enabled", True)),
        "allowed_tools": payload.get("allowed_tools") or [],
        "step_config": payload.get("step_config") or {},
    }
