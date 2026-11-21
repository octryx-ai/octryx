"""What an entry path asks turn preparation for, and what a prepared turn is.

Both entry paths build one :class:`TurnRequest`: ``/chat/api`` (send, continue, workflow
proposal decision, artifact action) and the services that start a chat turn
(coordinator continue, sub-agent resume, coding execution) use
``SESSION_SCOPE_OWN_OR_NEW``; ``/api/v1/sessions/{id}/messages`` uses
``SESSION_SCOPE_EXISTING`` (the named session must exist and be writable by the caller).
The ``*_explicit`` flags say which values the caller chose itself; an explicit value is
never replaced by a session, agent or Workspace default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..agent_mode import DEFAULT_AGENT_MODE_KEY

SESSION_SCOPE_OWN_OR_NEW = "own_or_new"
SESSION_SCOPE_EXISTING = "existing"
SessionScope = Literal["own_or_new", "existing"]


@dataclass(frozen=True, slots=True)
class TurnRequest:
    user_id: str
    prompt: str
    session_id: str = ""
    session_scope: SessionScope = SESSION_SCOPE_OWN_OR_NEW
    project_id: str = ""
    runtime_target_id: str = ""
    agent_id: str = ""
    # Empty means the session's agent type.
    agent_type: str = DEFAULT_AGENT_MODE_KEY
    # The key the client sent (mirrored on the session).
    workflow_key: str = ""
    workflow_decisions: dict[str, str] | None = None
    # A platform service that starts its own turn names itself here; routing selects that
    # service's workflow (``workflow_routing/platform_selection``, closed set) and makes no
    # proposal call. HTTP routes never set it.
    platform_workflow_service: str = ""
    agent_type_explicit: bool = False
    project_id_explicit: bool = False
    runtime_target_id_explicit: bool = False
    thinking_level_explicit: bool = False
    thinking_level: str = "light"
    idempotency_key: str | None = None
    # Applied to the session metadata in the preparing transaction, after the turn marker.
    session_metadata_patch: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PreparedTurn:
    """A committed, marked turn: ``running`` / ``in_progress``, owned by this process."""

    session_id: str
    user_message_id: str
    prompt: str
    project_id: str | None
    agent_type: str
    runtime_target_id: str | None
    thinking_level: str
    agent_definition: dict[str, Any] | None


__all__ = [
    "SESSION_SCOPE_EXISTING",
    "SESSION_SCOPE_OWN_OR_NEW",
    "PreparedTurn",
    "SessionScope",
    "TurnRequest",
]
