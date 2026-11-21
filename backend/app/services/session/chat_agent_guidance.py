"""Read-only chat guidance for a session's agents.

The chat bootstrap and the turn response carry one ``chatAgentGuidance`` object built here, so both
show the same identities. It answers three display questions and nothing else:

* which agent the *next* turn of this chat is bound to (``session_bound_agent_id``, by the runtime's own
  rule: an explicit empty binding is unbound, a one-turn mention never rebinds);
* which agent the *latest recorded turn* used (``agent_definition_id``). Preparation records it before
  the turn completes and a turn can fail, so it is not proof of which agent produced an answer;
* the declared tool surface of the next-turn agent's runtime content (published revision or live
  draft row, per ``agent_definition_execution_mode``).

Boundaries:

* Visibility is the chat runtime's owner scope. A deleted and a foreign definition look identical:
  ``unavailable`` with no name and no content. An owned inactive definition is ``inactive``.
* ``available`` means owned and active only. It is not admission and not a capability
  grant; a declared ``governed`` surface says nothing about which tools a turn will get.
* An unbound next turn is ``None``: the runtime may still apply a Workspace default agent, which is
  deliberately not predicted here.
* No writes, no prompt rendering, no authored content, no provider calls.
"""

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
    """The ``chatAgentGuidance`` payload for *session*, or for a new chat launched with *requested_agent_id*."""
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
    """The declared surface of the content a next turn would execute, or ``unknown`` with the reason."""
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
