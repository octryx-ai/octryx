"""The closed set of sources a turn's Agent Definition can come from."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

AGENT_SELECTION_SOURCE_METADATA_KEY = "agent_selection_source"
BOUND_AGENT_METADATA_KEY = "bound_agent_definition_id"


class AgentSelectionSource(StrEnum):
    WORKFLOW_PHASE = "workflow_phase"
    EXPLICIT = "explicit"
    MENTION = "mention"  # an exact ``@<configured name>`` mention of an owned agent
    SESSION = "session"
    DEFAULT = "default"  # the Workspace composition's default agent binding
    PLATFORM_DEFAULT = "platform_default"  # no pick: the platform Assistant
    NONE = "none"  # a turn recorded without an agent definition


AGENT_SELECTION_SOURCES = frozenset(source.value for source in AgentSelectionSource)


def session_bound_agent_id(metadata: dict[str, Any]) -> str:
    return str(metadata.get(BOUND_AGENT_METADATA_KEY) or "").strip()


def bound_agent_after_turn(*, previously_bound: str, source: AgentSelectionSource, turn_agent_id: str) -> str | None:
    if source == AgentSelectionSource.MENTION and previously_bound:
        return previously_bound
    return turn_agent_id or None


def closed_agent_selection_source(value: Any) -> str | None:
    return value if isinstance(value, str) and value in AGENT_SELECTION_SOURCES else None


__all__ = [
    "AGENT_SELECTION_SOURCES",
    "AGENT_SELECTION_SOURCE_METADATA_KEY",
    "BOUND_AGENT_METADATA_KEY",
    "AgentSelectionSource",
    "bound_agent_after_turn",
    "closed_agent_selection_source",
    "session_bound_agent_id",
]
