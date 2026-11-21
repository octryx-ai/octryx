"""The closed set of reasons a turn is refused before it starts.

Turn preparation (``turn_start.prepare_turn``) answers with a :class:`TurnRefusal` instead
of an HTTP error. :data:`REFUSAL_HTTP_STATUS` is the one status contract of both entry
paths; each path's thin adapter renders the body: ``web/_helpers/chat_turn_prepare`` keeps
the ``/chat/api`` plain-text details, ``api/routes/_sessions_turn_routes`` answers
``/api/v1`` with the state as a machine-readable ``code``. The request-bound services that
start a chat turn (coordinator continue, coding execution) keep the chat rendering they
always propagated.

``detail`` is the operator-facing text (or, for ``agent_definition_refused``, the typed
refusal record of). It never carries a prompt or an exception text.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TurnRefusalState(StrEnum):
    PROMPT_REQUIRED = "prompt_required"
    USER_NOT_FOUND = "user_not_found"
    SESSION_NOT_FOUND = "session_not_found"
    SESSION_ACCESS_DENIED = "session_access_denied"
    SESSION_ARCHIVED = "session_archived"
    TURN_ALREADY_RUNNING = "turn_already_running"
    DUPLICATE_TEXT = "duplicate_text"
    RUNTIME_TARGET_INVALID = "runtime_target_invalid"
    RUNTIME_NOT_ALLOWED = "runtime_not_allowed"
    RUNTIME_REQUIREMENT_UNMET = "runtime_requirement_unmet"
    AGENT_NOT_FOUND = "agent_not_found"
    AGENT_NOT_ALLOWED = "agent_not_allowed"
    AGENT_DEFINITION_REFUSED = "agent_definition_refused"
    AGENT_MENTION_AMBIGUOUS = "agent_mention_ambiguous"
    PROJECT_SELECTION_REQUIRED = "project_selection_required"
    PROJECT_NOT_ASSIGNED = "project_not_assigned"
    PROJECT_NOT_FOUND = "project_not_found"  # a named Workspace that does not exist or the caller is no member of
    PREPARATION_FAILED = "preparation_failed"


# The status each refusal answers with, on every entry path. The values are the ones
# ``/chat/api`` always answered; ``duplicate_text`` was an unhandled 500 before it had a state.
REFUSAL_HTTP_STATUS: dict[TurnRefusalState, int] = {
    TurnRefusalState.PROMPT_REQUIRED: 400,
    TurnRefusalState.USER_NOT_FOUND: 404,
    TurnRefusalState.SESSION_NOT_FOUND: 404,
    TurnRefusalState.SESSION_ACCESS_DENIED: 403,
    TurnRefusalState.SESSION_ARCHIVED: 409,
    TurnRefusalState.TURN_ALREADY_RUNNING: 409,
    TurnRefusalState.DUPLICATE_TEXT: 409,
    TurnRefusalState.RUNTIME_TARGET_INVALID: 400,
    TurnRefusalState.RUNTIME_NOT_ALLOWED: 403,
    TurnRefusalState.RUNTIME_REQUIREMENT_UNMET: 409,
    TurnRefusalState.AGENT_NOT_FOUND: 404,
    TurnRefusalState.AGENT_NOT_ALLOWED: 403,
    TurnRefusalState.AGENT_DEFINITION_REFUSED: 409,
    TurnRefusalState.AGENT_MENTION_AMBIGUOUS: 409,
    TurnRefusalState.PROJECT_SELECTION_REQUIRED: 400,
    TurnRefusalState.PROJECT_NOT_ASSIGNED: 403,
    TurnRefusalState.PROJECT_NOT_FOUND: 404,
    TurnRefusalState.PREPARATION_FAILED: 500,
}


@dataclass(frozen=True, slots=True)
class TurnRefusal:
    state: TurnRefusalState
    detail: str | dict[str, Any]

    @property
    def http_status(self) -> int:
        return REFUSAL_HTTP_STATUS[self.state]


class TurnRefusedError(Exception):
    """Internal control flow of preparation; the owner returns the carried :class:`TurnRefusal`."""

    def __init__(self, state: TurnRefusalState, detail: str | dict[str, Any]) -> None:
        self.refusal = TurnRefusal(state=state, detail=detail)
        super().__init__(state.value)


__all__ = ["REFUSAL_HTTP_STATUS", "TurnRefusal", "TurnRefusalState", "TurnRefusedError"]
