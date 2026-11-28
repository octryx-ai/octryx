"""The closed set of reasons a turn is refused before it starts."""

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
    RUNNER_REFUSED = "runner_refused"  # the runner turn the prepared message hands off to was refused


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
    TurnRefusalState.RUNNER_REFUSED: 409,
}


@dataclass(frozen=True, slots=True)
class TurnRefusal:
    state: TurnRefusalState
    detail: str | dict[str, Any]

    @property
    def http_status(self) -> int:
        return REFUSAL_HTTP_STATUS[self.state]


class TurnRefusedError(Exception):
    def __init__(self, state: TurnRefusalState, detail: str | dict[str, Any]) -> None:
        self.refusal = TurnRefusal(state=state, detail=detail)
        super().__init__(state.value)


__all__ = ["REFUSAL_HTTP_STATUS", "TurnRefusal", "TurnRefusalState", "TurnRefusedError"]
