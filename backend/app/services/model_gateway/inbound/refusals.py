"""Anthropic-shaped refusals of the inbound model gateway: an explicit (state, reason) and a fixed hint."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi.responses import JSONResponse

from ...agent_gateway.contract import (
    HEADER_GATEWAY_REASON,
    HEADER_GATEWAY_STATE,
    STATE_DENIED,
    STATE_NEEDS_CONFIGURATION,
    STATE_UNAUTHORIZED,
)
from ..litellm.errors import (
    GATEWAY_STATE_ALIAS_DENIED,
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
    GATEWAY_STATE_CONTENT_POLICY_DENIED,
    GATEWAY_STATE_CONTEXT_PRESSURE,
    GATEWAY_STATE_DATA_POLICY_DENIED,
    LiteLLMGatewayError,
)

ERROR_TYPE_AUTHENTICATION = "authentication_error"
ERROR_TYPE_PERMISSION = "permission_error"
ERROR_TYPE_INVALID_REQUEST = "invalid_request_error"
ERROR_TYPE_RATE_LIMIT = "rate_limit_error"
ERROR_TYPE_API = "api_error"
ERROR_TYPE_OVERLOADED = "overloaded_error"
ERROR_TYPE_NOT_FOUND = "not_found_error"
ANTHROPIC_ERROR_TYPES = frozenset(
    {
        ERROR_TYPE_AUTHENTICATION,
        ERROR_TYPE_PERMISSION,
        ERROR_TYPE_INVALID_REQUEST,
        ERROR_TYPE_RATE_LIMIT,
        ERROR_TYPE_API,
        ERROR_TYPE_OVERLOADED,
        ERROR_TYPE_NOT_FOUND,
    }
)

REASON_BODY_TOO_LARGE = "request_body_too_large"
REASON_BODY_INVALID = "request_body_invalid"
REASON_ALIAS_NOT_LISTED = "alias_not_listed"
REASON_ALIAS_PROVIDER_AMBIGUOUS = "alias_provider_ambiguous"
REASON_BUDGET_EXCEEDED = "budget_exceeded"
REASON_SECRET_DETECTED = "secret_detected_in_prompt"
REASON_COUNT_TOKENS_UNSUPPORTED = "count_tokens_not_supported"

_HINT_DEFAULT = "The request was not sent to the model."
# A model the Workspace does not admit, on either route; /model lists the ones it does.
MODEL_NOT_ADMITTED_HINT = "This Workspace does not offer this model. Run /model to see the models it offers."
_HINTS: dict[str, str] = {
    REASON_SECRET_DETECTED: (
        "This request contains what looks like a secret; it was not sent to the model. Remove the affected "
        "message or start a new conversation (Claude Code: /rewind or /clear; Codex: start a new session)."
    ),
    REASON_BUDGET_EXCEEDED: "A budget policy blocks further model calls. Ask your Octryx administrator.",
    REASON_ALIAS_NOT_LISTED: MODEL_NOT_ADMITTED_HINT,
    REASON_ALIAS_PROVIDER_AMBIGUOUS: (
        "More than one gateway provider lists this model alias. An administrator must resolve it."
    ),
    REASON_BODY_TOO_LARGE: "The request body exceeds the gateway limit. Compact the conversation and retry.",
    REASON_BODY_INVALID: "The request body is not a valid Anthropic Messages request.",
    REASON_COUNT_TOKENS_UNSUPPORTED: "Token counting is not available through this gateway.",
}
_STATE_HINTS: dict[str, str] = {
    STATE_UNAUTHORIZED: "Sign in again with octryx-claude.",
    STATE_NEEDS_CONFIGURATION: "The gateway or Workspace configuration is incomplete. Ask your administrator.",
    STATE_DENIED: "The Workspace policy does not allow this request.",
}

# A policy block is a non-retried 4xx (a budget is 403, not 429: retrying cannot lift it); an upstream 429/5xx/529 keeps
# its status so the client backs off as against the Anthropic API.
_STATUS_FOR_STATE = {STATE_UNAUTHORIZED: 401, STATE_DENIED: 403, STATE_NEEDS_CONFIGURATION: 400}
_TYPE_FOR_STATUS = {
    400: ERROR_TYPE_INVALID_REQUEST,
    401: ERROR_TYPE_AUTHENTICATION,
    403: ERROR_TYPE_PERMISSION,
    404: ERROR_TYPE_NOT_FOUND,
    413: ERROR_TYPE_INVALID_REQUEST,
    429: ERROR_TYPE_RATE_LIMIT,
    529: ERROR_TYPE_OVERLOADED,
}

# Admission-time gateway states that are policy decisions rather than gaps.
_POLICY_GATEWAY_STATES = frozenset(
    {GATEWAY_STATE_ALIAS_DENIED, GATEWAY_STATE_DATA_POLICY_DENIED, GATEWAY_STATE_CONTENT_POLICY_DENIED,
     GATEWAY_STATE_CAPABILITY_NOT_PROVEN}
)


def error_type_for_status(status: int) -> str:
    if status in _TYPE_FOR_STATUS:
        return _TYPE_FOR_STATUS[status]
    return ERROR_TYPE_API if status >= 500 else ERROR_TYPE_INVALID_REQUEST


@dataclass(frozen=True, slots=True)
class InboundRefusal:
    state: str
    reason: str
    http_status: int
    hint: str = ""
    # Allowlisted upstream headers (retry-after, rate limits, request id) only.
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def error_type(self) -> str:
        return error_type_for_status(self.http_status)

    @property
    def hint_text(self) -> str:
        return self.hint or _HINTS.get(self.reason) or _STATE_HINTS.get(self.state) or _HINT_DEFAULT

    def message(self) -> str:
        return f"Octryx gateway: {self.state} ({self.reason}). {self.hint_text}"


# The client sees the state, the reason and a fixed hint: never text derived from a prompt, an upstream body or an
# exception.
def refusal(state: str, reason: str, *, http_status: int | None = None, hint: str = "") -> InboundRefusal:
    return InboundRefusal(
        state=state,
        reason=reason,
        http_status=http_status or _STATUS_FOR_STATE.get(state, 400),
        hint=hint,
    )


def refusal_for_admission_error(exc: LiteLLMGatewayError) -> InboundRefusal:
    reason = exc.denial_reason or exc.gateway_state
    if exc.gateway_state == GATEWAY_STATE_ALIAS_DENIED:
        return refusal(STATE_DENIED, reason, hint=MODEL_NOT_ADMITTED_HINT)
    if exc.gateway_state in _POLICY_GATEWAY_STATES:
        return refusal(STATE_DENIED, reason)
    return refusal(STATE_NEEDS_CONFIGURATION, reason)


def anthropic_error_response(item: InboundRefusal) -> JSONResponse:
    return JSONResponse(
        status_code=item.http_status,
        content={"type": "error", "error": {"type": item.error_type, "message": item.message()}},
        headers={
            **dict(item.headers),
            HEADER_GATEWAY_STATE: item.state,
            HEADER_GATEWAY_REASON: item.reason,
        },
    )


# OpenAI error shape (the ``/openai`` Responses route for Codex). ``code`` is the gateway reason, except for a
# context-window overflow: Codex compacts on ``context_length_exceeded`` and only on that code.
OPENAI_ERROR_TYPE_SERVER = "server_error"
OPENAI_CONTEXT_LENGTH_CODE = "context_length_exceeded"
_OPENAI_TYPE_FOR_STATUS = {
    400: ERROR_TYPE_INVALID_REQUEST,
    401: ERROR_TYPE_AUTHENTICATION,
    403: ERROR_TYPE_PERMISSION,
    404: ERROR_TYPE_NOT_FOUND,
    413: ERROR_TYPE_INVALID_REQUEST,
    429: "rate_limit_error",
}


def openai_error_type_for_status(status: int) -> str:
    if status in _OPENAI_TYPE_FOR_STATUS:
        return _OPENAI_TYPE_FOR_STATUS[status]
    return OPENAI_ERROR_TYPE_SERVER if status >= 500 else ERROR_TYPE_INVALID_REQUEST


def openai_error_code(item: InboundRefusal) -> str:
    return OPENAI_CONTEXT_LENGTH_CODE if item.state == GATEWAY_STATE_CONTEXT_PRESSURE else item.reason


def openai_error_response(item: InboundRefusal) -> JSONResponse:
    return JSONResponse(
        status_code=item.http_status,
        content={"error": {"message": item.message(), "type": openai_error_type_for_status(item.http_status),
                           "param": None, "code": openai_error_code(item)}},
        headers={
            **dict(item.headers),
            HEADER_GATEWAY_STATE: item.state,
            HEADER_GATEWAY_REASON: item.reason,
        },
    )


__all__ = [
    "ANTHROPIC_ERROR_TYPES",
    "ERROR_TYPE_API",
    "ERROR_TYPE_AUTHENTICATION",
    "ERROR_TYPE_INVALID_REQUEST",
    "ERROR_TYPE_NOT_FOUND",
    "ERROR_TYPE_OVERLOADED",
    "ERROR_TYPE_PERMISSION",
    "ERROR_TYPE_RATE_LIMIT",
    "MODEL_NOT_ADMITTED_HINT",
    "OPENAI_CONTEXT_LENGTH_CODE",
    "REASON_ALIAS_NOT_LISTED",
    "REASON_ALIAS_PROVIDER_AMBIGUOUS",
    "REASON_BODY_INVALID",
    "REASON_BODY_TOO_LARGE",
    "REASON_BUDGET_EXCEEDED",
    "REASON_COUNT_TOKENS_UNSUPPORTED",
    "REASON_SECRET_DETECTED",
    "InboundRefusal",
    "anthropic_error_response",
    "error_type_for_status",
    "openai_error_code",
    "openai_error_response",
    "refusal",
    "refusal_for_admission_error",
]
