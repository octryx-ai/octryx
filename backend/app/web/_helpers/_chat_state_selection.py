"""Selection state helpers for the chat payload builder."""

from dataclasses import dataclass

from ...models import AgentDefinition
from ...services.agent_mode import DEFAULT_AGENT_MODE_KEY
from ...services.session.agent_selection_sources import (
    AGENT_SELECTION_SOURCE_METADATA_KEY,
    closed_agent_selection_source,
)


@dataclass(frozen=True)
class ChatSelectionState:
    selected_agent_id: str
    selected_agent_name: str
    selected_agent_type: str
    selected_agent_selection_source: str


def build_chat_selection_state(
    *,
    selected_session_metadata: dict | None,
    selected_session_exists: bool,
    selected_agent_id: str,
    selected_agent: AgentDefinition | None,
    selected_agent_type: str,
    selected_agent_type_explicit: bool,
    default_selection: dict,
) -> ChatSelectionState:
    metadata = selected_session_metadata or {}
    default_agent_type = str(default_selection.get("selected_agent_type") or DEFAULT_AGENT_MODE_KEY).strip()
    explicit_agent_selected = bool(str(selected_agent_id or "").strip()) and selected_agent is not None

    return ChatSelectionState(
        selected_agent_id=(
            str(selected_agent_id or "").strip()
            if selected_session_exists or explicit_agent_selected
            else str(default_selection.get("selected_agent_id") or "").strip()
        ),
        selected_agent_name=(
            (selected_agent.name if selected_agent else "")
            if selected_session_exists or explicit_agent_selected
            else str(default_selection.get("selected_agent_name") or "").strip()
        ),
        selected_agent_type=(
            str(selected_agent_type or DEFAULT_AGENT_MODE_KEY).strip()
            if selected_session_exists or explicit_agent_selected or selected_agent_type_explicit
            else default_agent_type
        ),
        selected_agent_selection_source=(
            (closed_agent_selection_source(metadata.get(AGENT_SELECTION_SOURCE_METADATA_KEY)) or "")
            if selected_session_exists
            else ""
        ),
    )
