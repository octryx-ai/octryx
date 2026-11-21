"""The closed set of sources a turn's Agent Definition can come from.

Turn preparation (``turn_agent_selection``) records exactly one of these on the session
(``AGENT_SELECTION_SOURCE_METADATA_KEY``); the turn execution snapshot and summary carry it
so a trace says why the turn ran with (or without) an agent. There is no scored or
prompt-derived source: an agent is chosen explicitly, named by an exact ``@mention``,
carried by the session, or configured as the Workspace default.

The session's *bound* agent (``BOUND_AGENT_METADATA_KEY``) is what later turns reuse. A
mention overrides it for its own turn only; every other source binds the
turn's agent, and a mention in a session without a bound agent binds the mentioned one.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

AGENT_SELECTION_SOURCE_METADATA_KEY = "agent_selection_source"
BOUND_AGENT_METADATA_KEY = "bound_agent_definition_id"


class AgentSelectionSource(StrEnum):
    WORKFLOW_PHASE = "workflow_phase"  # the agent the run's current phase names
    EXPLICIT = "explicit"  # the caller's ``agent_id``
    MENTION = "mention"  # an exact ``@<configured name>`` mention of an owned agent
    SESSION = "session"  # the agent the session is bound to
    DEFAULT = "default"  # the Workspace composition's default agent binding
    PLATFORM_DEFAULT = "platform_default"  # no pick: the platform Assistant
    NONE = "none"  # a turn recorded without an agent definition


AGENT_SELECTION_SOURCES = frozenset(source.value for source in AgentSelectionSource)


def session_bound_agent_id(metadata: dict[str, Any]) -> str:
    """The agent a session is bound to (empty when it is not bound)."""
    return str(metadata.get(BOUND_AGENT_METADATA_KEY) or "").strip()


def bound_agent_after_turn(*, previously_bound: str, source: AgentSelectionSource, turn_agent_id: str) -> str | None:
    """The session's bound agent after a turn: a mention keeps an existing binding."""
    if source == AgentSelectionSource.MENTION and previously_bound:
        return previously_bound
    return turn_agent_id or None


def closed_agent_selection_source(value: Any) -> str | None:
    """``value`` when it is one of the closed sources; ``None`` for any other value."""
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
