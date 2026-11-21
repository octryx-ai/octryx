"""Explicit runtime resolution of an Agent Definition.

Without this module the runtime would execute the mutable
``AgentDefinition`` / ``AgentStep`` rows directly: call sites would query the live row,
serialize it, and run it. Publication would then decide nothing, because nothing
at execution time would look at a published revision.

Resolution is always one of two **named** modes, read from the system-config
key ``agent_definition_execution_mode``:

``published``
    The execution payload is built from the highest-numbered published
    revision's snapshot. The live row is read only for identity, ownership, and
    the group label — never for authored content, so a definition that was
    published and then edited through the panel executes the *published* content.
    A definition with no published revision is the explicit outcome
    ``needs_publication``. There is no fallback of any kind.

``draft``
    The live row is the authored source, recorded as ``live_draft_row``.

**When the key is unset the mode is** ``draft``**: the authoring default.** An
administrator saves a definition in the Agent Designer and chats run what was saved;
publishing records a revision, and the platform opts into running only published
revisions by setting this key to ``published``. Platform agents are outside that choice:
they always execute their published (four-eyes) revision, whatever the key says.

A key that is *set* to anything else is a misconfiguration:
resolution then yields ``needs_configuration`` and refuses, because falling back to
``draft`` there would let a typo silently downgrade a platform that an
administrator meant to run on published content. Only the absent key gets the
documented default.

In both modes the live row's ``is_active`` is the admission switch: a
definition that is inactive *now* resolves to the explicit refusal ``inactive``,
whatever its draft or published content says — a revision snapshotted while it was
active does not revive it. Ownership is checked first, so another owner's inactive
definition stays ``not_found``. The check admits new executions only; a turn already
running is not cancelled.

Every resolution carries its mode and source on the returned object, as payload
keys, and — via :data:`RESOLUTION_METADATA_KEY` — in the canonical session,
task-run, and turn-trace metadata, so what executed is recorded rather than
assumed.
"""

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
    """Read the platform execution mode.

    An absent key is the authoring default, ``draft``. A key set to anything
    else raises :class:`AgentDefinitionExecutionModeError` — see the module docstring
    for why that is not allowed to degrade into the default.
    """
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
    """Say which content a run of *definition_id* executes, for display only.

    ``draft`` mode runs the live row (saved settings and steps, published or not);
    ``published`` mode runs the published revision, or refuses with
    ``needs_publication`` when there is none. An invalid mode is ``unknown``.
    """
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
    """Resolve *definition_id* into an execution payload, or an explicit refusal.

    *visible_to_user_id* scopes the lookup to the agents that user may see (
    ``agent_visibility``: own, Workspace-shared, global, built-in); without it the
    lookup is unscoped. *workspace_id* further limits it to global, built-in and that Workspace's agents
    (a turn in Workspace A never runs Workspace B's agent). This function changes which *content* executes.
    """
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
