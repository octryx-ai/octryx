"""Read-only chat guidance for a session's agents: the next turn's agent, the latest turn's and its tool surface."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_definition_execution_states import EXECUTION_MODE_PUBLISHED, AgentDefinitionExecutionModeError
from app.services.agent_definition_revision_store import get_published_revision
from app.services.agent_tool_surface_contract import TOOL_SURFACES, live_row_tool_surface, snapshot_tool_surface

from ...models import AgentDefinition
from ...models import Session as AgentSession
from ..agent_definition_execution import get_agent_definition_execution_mode
from ..agent_definition_snapshot import snapshot_header
from ..agent_visibility import visible_agent_clause
from .agent_selection_sources import (
    AGENT_SELECTION_SOURCE_METADATA_KEY,
    closed_agent_selection_source,
    session_bound_agent_id,
)

CHAT_AGENT_GUIDANCE_KEY = "chatAgentGuidance"
CONTRACT_VERSION = 1

AVAILABLE = "available"
INACTIVE = "inactive"
UNAVAILABLE = "unavailable"

NEXT_SOURCE_SESSION_BINDING = "session_binding"
NEXT_SOURCE_LAUNCH_REQUEST = "launch_request"
NEXT_SOURCE_NONE = "none"

SURFACE_UNKNOWN = "unknown"
CONTENT_PUBLISHED_REVISION = "published_revision"
CONTENT_LIVE_DRAFT_ROW = "live_draft_row"
CONTENT_NEEDS_PUBLICATION = "needs_publication"
CONTENT_UNKNOWN = "unknown"

__all__ = ["CHAT_AGENT_GUIDANCE_KEY", "project_chat_agent_guidance"]


async def project_chat_agent_guidance(
    db: AsyncSession,
    *,
    user_id: str,
    session: AgentSession | None,
    requested_agent_id: str = "",
) -> dict[str, Any]:
    metadata = dict(session.metadata_ or {}) if session is not None else {}
    if session is not None:
        next_id = session_bound_agent_id(metadata)
        next_source = NEXT_SOURCE_SESSION_BINDING if next_id else NEXT_SOURCE_NONE
        latest_id = str(metadata.get("agent_definition_id") or "").strip()
        latest_source = closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY))
    else:
        next_id = str(requested_agent_id or "").strip()
        next_source = NEXT_SOURCE_LAUNCH_REQUEST if next_id else NEXT_SOURCE_NONE
        latest_id = ""
        latest_source = None

    owned = await _owned_definitions(db, user_id=user_id, definition_ids={next_id, latest_id} - {""})
    next_agent = _identity(next_id, owned.get(next_id))
    tool_surface, content_source = SURFACE_UNKNOWN, CONTENT_UNKNOWN
    if next_agent is not None and next_agent["availability"] == AVAILABLE:
        tool_surface, content_source = await _declared_surface(db, owned[next_id])
    return {
        "contractVersion": CONTRACT_VERSION,
        "sessionId": session.id if session is not None else None,
        "nextTurnAgent": next_agent,
        "nextTurnAgentSource": next_source,
        "lastTurnAgent": _identity(latest_id, owned.get(latest_id)),
        "lastTurnSelectionSource": latest_source,
        "toolSurface": tool_surface,
        "contentSource": content_source,
    }


async def _owned_definitions(
    db: AsyncSession, *, user_id: str, definition_ids: set[str]
) -> dict[str, AgentDefinition]:
    if not definition_ids or not user_id:
        return {}
    rows = await db.execute(
        select(AgentDefinition).where(
            AgentDefinition.id.in_(definition_ids), await visible_agent_clause(db, user_id)
        )
    )
    return {row.id: row for row in rows.scalars().all()}


def _identity(definition_id: str, definition: AgentDefinition | None) -> dict[str, Any] | None:
    if not definition_id:
        return None
    if definition is None:
        # Deleted or not owned: the caller's own reference is echoed, nothing about the definition.
        return {"id": definition_id, "name": None, "availability": UNAVAILABLE}
    # Same switch as admission: only a truthy live ``is_active`` counts as active.
    availability = AVAILABLE if definition.is_active else INACTIVE
    return {"id": definition.id, "name": definition.name or "", "availability": availability}


async def _declared_surface(db: AsyncSession, definition: AgentDefinition) -> tuple[str, str]:
    try:
        mode = await get_agent_definition_execution_mode(db)
    except AgentDefinitionExecutionModeError:
        return SURFACE_UNKNOWN, CONTENT_UNKNOWN
    if mode == EXECUTION_MODE_PUBLISHED:
        revision = await get_published_revision(db, definition.id)
        if revision is None:
            return SURFACE_UNKNOWN, CONTENT_NEEDS_PUBLICATION
        value = snapshot_tool_surface(snapshot_header(revision.snapshot or {}))
        content_source = CONTENT_PUBLISHED_REVISION
    else:
        value = live_row_tool_surface(definition.tool_surface)
        content_source = CONTENT_LIVE_DRAFT_ROW
    # A present value outside the enum fails closed at runtime; it is never shown as a known surface.
    return (value if value in TOOL_SURFACES else SURFACE_UNKNOWN), content_source
