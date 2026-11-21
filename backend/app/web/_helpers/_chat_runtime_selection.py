"""Agent, runtime and thinking selection for a chat payload (bootstrap and selected-session view)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentDefinition, User
from ...models import Session as AgentSession
from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY, resolve_agent_mode
from ...services.agent_visibility import visible_agent_clause
from ...services.session.turn_runtime_selection import sticky_session_runtime_target_id
from ...services.workspace_composition import get_workspace_execution_view

__all__ = ["ChatRuntimeSelection", "resolve_chat_runtime_selection"]

AUTOMATIC_RUNTIME_LABEL = "Automatic fallback chain"
DEFAULT_THINKING_LEVEL = "light"


@dataclass(slots=True)
class ChatRuntimeSelection:
    selected_agent_id: str
    selected_agent: AgentDefinition | None
    selected_agent_type: str
    selected_agent_type_explicit: bool
    selected_project_id: str
    runtime_options: list[dict[str, Any]]
    selected_runtime_target_id: str
    selected_runtime_label: str
    selected_thinking_level: str


async def resolve_chat_runtime_selection(
    db: AsyncSession,
    *,
    user: User,
    selected_session: AgentSession | None,
    new_thread: bool = False,
    project_id: str = "",
    runtime_target_id: str = "",
    agent_id: str = "",
    agent_type: str = "",
) -> ChatRuntimeSelection:
    """The selection the composer shows: the selected session's own choices, else the requested ones."""
    from app.services.runtime_options import list_chat_runtime_options

    session_selected = bool(selected_session and not new_thread)
    selected_agent_id = agent_id
    selected_agent = None
    requested_mode = await resolve_agent_mode(db, agent_type or DEFAULT_AGENT_MODE_KEY)
    if session_selected:
        selected_agent_id = str((selected_session.metadata_ or {}).get("agent_definition_id") or "")
    if selected_agent_id:
        selected_agent = (
            await db.execute(
                select(AgentDefinition)
                .where(
                    AgentDefinition.id == selected_agent_id,
                    await visible_agent_clause(db, user.id),
                )
                .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
            )
        ).scalar_one_or_none()
    selected_project_id = project_id or (
        selected_session.project_id if selected_session and selected_session.project_id else ""
    )
    if not selected_project_id and selected_agent and selected_agent.project_id:
        selected_project_id = selected_agent.project_id
    workspace_execution_view = (
        await get_workspace_execution_view(db, workspace_id=selected_project_id) if selected_project_id else None
    )
    # The pill shows a model only when a person chose it: an agent pin or the Workspace default
    # is an implicit source the server resolves per turn; pre-filling it would send it back as an explicit choice.
    selected_runtime_target_id = str(runtime_target_id or "").strip()
    selected_thinking_level = DEFAULT_THINKING_LEVEL
    selected_agent_type = requested_mode.key
    if session_selected:
        selected_runtime_target_id = sticky_session_runtime_target_id(selected_session)
        selected_thinking_level = str(
            (selected_session.metadata_ or {}).get("thinking_level") or DEFAULT_THINKING_LEVEL
        )
        selected_agent_type = str(selected_session.agent_type or DEFAULT_AGENT_MODE_KEY)
    elif selected_agent and selected_agent.thinking_level:
        selected_thinking_level = selected_agent.thinking_level
        selected_agent_type = str(selected_agent.agent_type or requested_mode.key or DEFAULT_AGENT_MODE_KEY)
    runtime_options = await list_chat_runtime_options(
        db,
        workspace_execution_view=workspace_execution_view,
        include_runtime_target_id=selected_runtime_target_id,
    )
    runtime_label_by_id = {option["value"]: option["label"] for option in runtime_options}
    automatic_runtime_label = runtime_label_by_id.get("", AUTOMATIC_RUNTIME_LABEL)
    session_runtime_label = (
        str((selected_session.metadata_ or {}).get("runtime_label") or "").strip() if session_selected else ""
    )
    selected_runtime_label = runtime_label_by_id.get(selected_runtime_target_id, automatic_runtime_label)
    if selected_runtime_target_id and session_runtime_label:
        selected_runtime_label = runtime_label_by_id.get(selected_runtime_target_id, session_runtime_label)
    return ChatRuntimeSelection(
        selected_agent_id=selected_agent_id,
        selected_agent=selected_agent,
        selected_agent_type=selected_agent_type,
        selected_agent_type_explicit=bool(str(agent_type or "").strip()),
        selected_project_id=selected_project_id,
        runtime_options=runtime_options,
        selected_runtime_target_id=selected_runtime_target_id,
        selected_runtime_label=selected_runtime_label,
        selected_thinking_level=selected_thinking_level,
    )
