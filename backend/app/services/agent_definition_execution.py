"""Explicit runtime resolution of an Agent Definition. The runtime never executes the mutable live rows directly:
resolution decides which content runs."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import AgentDefinition
from .agent_definition_execution_sources import resolve_live as _resolve_live
from .agent_definition_execution_sources import resolve_published as _resolve_published
from .agent_definition_execution_states import (
    AGENT_DEFINITION_EXECUTION_MODE_KEY,
    EXECUTION_MODE_DEFAULT,
    EXECUTION_MODE_PUBLISHED,
    EXECUTION_MODE_UNKNOWN,
    EXECUTION_MODES,
    STATUS_INACTIVE,
    STATUS_NEEDS_CONFIGURATION,
    STATUS_NOT_FOUND,
    AgentDefinitionExecutionModeError,
    AgentDefinitionResolution,
)
from .agent_definition_revision_store import get_published_revision
from .agent_visibility import visible_agent_clause, workspace_agent_clause
from .system_config.values import get_system_config_value

logger = logging.getLogger(__name__)


async def get_agent_definition_execution_mode(db: AsyncSession) -> str:
    # An invalid mode raises instead of degrading to the ``draft`` default.
    raw_value = (
        str(await get_system_config_value(db, AGENT_DEFINITION_EXECUTION_MODE_KEY) or "")
        .strip()
        .lower()
    )
    if raw_value in EXECUTION_MODES:
        return raw_value
    if raw_value:
        logger.error(
            "%s is set to a value that is not one of %s; refusing execution",
            AGENT_DEFINITION_EXECUTION_MODE_KEY,
            sorted(EXECUTION_MODES),
        )
        raise AgentDefinitionExecutionModeError
    return EXECUTION_MODE_DEFAULT


async def describe_execution_source(db: AsyncSession, definition_id: str) -> dict[str, Any]:
    try:
        mode = await get_agent_definition_execution_mode(db)
    except AgentDefinitionExecutionModeError:
        return {"mode": EXECUTION_MODE_UNKNOWN, "published_revision_number": None}
    published = await get_published_revision(db, definition_id)
    return {
        "mode": mode,
        "published_revision_number": int(published.revision_number) if published is not None else None,
    }


async def resolve_agent_definition_for_execution(
    db: AsyncSession,
    *,
    definition_id: str,
    visible_to_user_id: str | None = None,
    workspace_id: str | None = None,
) -> AgentDefinitionResolution:
    # ``workspace_id`` limits the lookup, so a turn in one Workspace never runs another Workspace's agent.
    resolved_id = str(definition_id or "").strip()
    try:
        mode = await get_agent_definition_execution_mode(db)
    except AgentDefinitionExecutionModeError:
        # An explicitly unknown mode is a configuration refusal on every path.
        return AgentDefinitionResolution(
            definition_id=resolved_id,
            mode=EXECUTION_MODE_UNKNOWN,
            status=STATUS_NEEDS_CONFIGURATION,
        )
    if not resolved_id:
        return AgentDefinitionResolution(
            definition_id="", mode=mode, status=STATUS_NOT_FOUND
        )

    stmt = (
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(AgentDefinition.id == resolved_id)
    )
    if visible_to_user_id:
        stmt = stmt.where(await visible_agent_clause(db, visible_to_user_id))
    if workspace_id:
        stmt = stmt.where(workspace_agent_clause(workspace_id))
    definition = (await db.execute(stmt)).scalar_one_or_none()
    if definition is None:
        return AgentDefinitionResolution(
            definition_id=resolved_id, mode=mode, status=STATUS_NOT_FOUND
        )
    if not definition.is_active:
        # Admission reads the live switch, never the content: no payload is built.
        return AgentDefinitionResolution(
            definition_id=definition.id, mode=mode, status=STATUS_INACTIVE
        )

    from .platform_agents.catalog import is_platform_agent_key

    # A platform agent always executes its published (four-eyes) revision; the platform mode governs
    # every other agent and never bypasses the platform publish boundary.
    if mode == EXECUTION_MODE_PUBLISHED or is_platform_agent_key(definition.builtin_key):
        return await _resolve_published(db, definition=definition, mode=mode)
    return await _resolve_live(db, definition=definition, mode=mode)


__all__ = [
    "get_agent_definition_execution_mode",
    "resolve_agent_definition_for_execution",
]
