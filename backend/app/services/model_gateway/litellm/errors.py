"""Fixed-message error contract for the governed LiteLLM gateway client."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.agent.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    CLASSIFICATION_SOURCE_EXPLICIT,
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_CONTENT_POLICY_DENIED,
    RUNTIME_ERROR_CONTEXT_PRESSURE,
    RUNTIME_ERROR_CONTRACT_VIOLATION,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
    RUNTIME_ERROR_FALLBACK_VIOLATION,
    RUNTIME_ERROR_PERMANENT,
    RUNTIME_ERROR_PROVIDER_INIT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    RUNTIME_ERROR_UNREACHABLE,
    ProviderRuntimeError,
    transport_error_class,
)

GATEWAY_STATE_ENDPOINT_DENIED = "endpoint_denied"
GATEWAY_STATE_VIRTUAL_KEY_MISSING = "virtual_key_missing"
GATEWAY_STATE_ALIAS_DENIED = "alias_denied"
# The workspace's server-owned data classification is not permitted for the
# alias' declared ``data_policy_class``. Its own state so the refusal is
# not read as a missing alias grant.
GATEWAY_STATE_DATA_POLICY_DENIED = "data_policy_denied"
# A content policy refused the request for what it contains; terminal, see runtime_errors.
GATEWAY_STATE_CONTENT_POLICY_DENIED = "content_policy_denied"
GATEWAY_STATE_CAPABILITY_NOT_PROVEN = "capability_not_proven"
GATEWAY_STATE_CONTEXT_PRESSURE = "context_pressure"
GATEWAY_STATE_UNAUTHORIZED = "gateway_unauthorized"
GATEWAY_STATE_RATE_LIMITED = "gateway_rate_limited"
GATEWAY_STATE_UNAVAILABLE = "gateway_unavailable"
GATEWAY_STATE_UNREACHABLE = "gateway_unreachable"
GATEWAY_STATE_TIMEOUT = "gateway_timeout"
# Configuration/probe denials happen before any billable chat request, so they
# stay fallbackable: a gateway configuration gap must not hard-fail a runtime
# chain that still has other targets.
GATEWAY_STATE_CONFIGURATION_INVALID = "configuration_invalid"
# The gateway rejected the request itself (4xx that is not auth/rate/timeout).
# Nothing was served, so another runtime may still be tried.
GATEWAY_STATE_REQUEST_REJECTED = "request_rejected"
# The gateway already served (and therefore already billed) a response that
# violates the pinned contract. Retrying or falling back would buy a second
# billable answer for a deterministic defect, so this state is terminal.
GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION = "response_contract_violation"
GATEWAY_STATE_FALLBACK_VIOLATION = "fallback_violation"

GATEWAY_STATES = (
    GATEWAY_STATE_ENDPOINT_DENIED,
    GATEWAY_STATE_VIRTUAL_KEY_MISSING,
    GATEWAY_STATE_ALIAS_DENIED,
    GATEWAY_STATE_DATA_POLICY_DENIED,
    GATEWAY_STATE_CONTENT_POLICY_DENIED,
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN,
    GATEWAY_STATE_CONTEXT_PRESSURE,
    GATEWAY_STATE_UNAUTHORIZED,
    GATEWAY_STATE_RATE_LIMITED,
    GATEWAY_STATE_UNAVAILABLE,
    GATEWAY_STATE_UNREACHABLE,
    GATEWAY_STATE_TIMEOUT,
    GATEWAY_STATE_CONFIGURATION_INVALID,
    GATEWAY_STATE_REQUEST_REJECTED,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION,
    GATEWAY_STATE_FALLBACK_VIOLATION,
)

# One fixed message per state. No interpolation, ever.
_STATE_MESSAGES: dict[str, str] = {
    GATEWAY_STATE_ENDPOINT_DENIED: "LiteLLM gateway endpoint rejected by endpoint policy.",
    GATEWAY_STATE_VIRTUAL_KEY_MISSING: "LiteLLM gateway virtual key is not configured.",
    GATEWAY_STATE_ALIAS_DENIED: "Requested model alias is not admitted for this LiteLLM gateway.",
    GATEWAY_STATE_DATA_POLICY_DENIED: (
        "Workspace data classification is not permitted for this LiteLLM gateway alias."
    ),
    GATEWAY_STATE_CONTENT_POLICY_DENIED: "A content policy does not allow this request on this LiteLLM gateway alias.",
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN: "Requested capability is not proven for this LiteLLM gateway alias.",
    GATEWAY_STATE_CONTEXT_PRESSURE: "LiteLLM gateway reported a context window limit for this request.",
    GATEWAY_STATE_UNAUTHORIZED: "LiteLLM gateway denied the virtual key.",
    GATEWAY_STATE_RATE_LIMITED: "LiteLLM gateway rate limited this request.",
    GATEWAY_STATE_UNAVAILABLE: "LiteLLM gateway is currently unavailable.",
    GATEWAY_STATE_UNREACHABLE: "LiteLLM gateway is unreachable.",
    GATEWAY_STATE_TIMEOUT: "LiteLLM gateway request timed out.",
    GATEWAY_STATE_CONFIGURATION_INVALID: "LiteLLM gateway configuration is incomplete or not pinned.",
    GATEWAY_STATE_REQUEST_REJECTED: "LiteLLM gateway rejected the request.",
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION: (
        "LiteLLM gateway response violated the pinned response contract; response discarded."
    ),
    GATEWAY_STATE_FALLBACK_VIOLATION: (
        "LiteLLM gateway returned a different model group than the admitted alias; response discarded."
    ),
}

_STATE_ERROR_CLASSES: dict[str, str] = {
    GATEWAY_STATE_ENDPOINT_DENIED: RUNTIME_ERROR_PROVIDER_INIT,
    GATEWAY_STATE_VIRTUAL_KEY_MISSING: RUNTIME_ERROR_PROVIDER_INIT,
    GATEWAY_STATE_ALIAS_DENIED: RUNTIME_ERROR_ALIAS_DENIED,
    GATEWAY_STATE_DATA_POLICY_DENIED: RUNTIME_ERROR_DATA_POLICY_DENIED,
    GATEWAY_STATE_CONTENT_POLICY_DENIED: RUNTIME_ERROR_CONTENT_POLICY_DENIED,
    GATEWAY_STATE_CAPABILITY_NOT_PROVEN: RUNTIME_ERROR_ALIAS_DENIED,
    GATEWAY_STATE_CONTEXT_PRESSURE: RUNTIME_ERROR_CONTEXT_PRESSURE,
    GATEWAY_STATE_UNAUTHORIZED: RUNTIME_ERROR_PERMANENT,
    GATEWAY_STATE_RATE_LIMITED: RUNTIME_ERROR_TRANSIENT,
    GATEWAY_STATE_UNAVAILABLE: RUNTIME_ERROR_TRANSIENT,
    GATEWAY_STATE_UNREACHABLE: RUNTIME_ERROR_UNREACHABLE,
    GATEWAY_STATE_TIMEOUT: RUNTIME_ERROR_TIMEOUT,
    GATEWAY_STATE_CONFIGURATION_INVALID: RUNTIME_ERROR_PROVIDER_INIT,
    GATEWAY_STATE_REQUEST_REJECTED: RUNTIME_ERROR_PERMANENT,
    GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION: RUNTIME_ERROR_CONTRACT_VIOLATION,
    GATEWAY_STATE_FALLBACK_VIOLATION: RUNTIME_ERROR_FALLBACK_VIOLATION,
}


# A denial reason is an audit code defined by this package. The charset guard
# makes that structural: anything that is not a lowercase snake_case token is
# dropped, so no remote payload can ever reach an error message.
_DENIAL_REASON_RE = re.compile(r"^[a-z0-9_]{1,64}$")


def normalize_denial_reason(value: object) -> str:
    candidate = value.strip() if isinstance(value, str) else ""
    return candidate if _DENIAL_REASON_RE.match(candidate) else ""


def _safe_detail(state: str, reason: str, status_code: int | None, upstream_detail: str) -> str:
    head = state + (f"/{reason}" if reason else "") + (f" (HTTP {int(status_code)})" if status_code is not None else "")
    return f"{head}: {upstream_detail}" if upstream_detail else head


class LiteLLMGatewayError(ProviderRuntimeError):
    """A typed gateway failure: a stable state and a fixed message plus at most a closed ``denial_reason`` code.
    The sanitized ``upstream_detail`` never enters the message, only ``safe_detail``."""

    def __init__(
        self,
        state: str,
        *,
        denial_reason: str = "",
        status_code: int | None = None,
        error_class_source: str = CLASSIFICATION_SOURCE_EXPLICIT,
        upstream_detail: str = "",
        content_notice: Mapping[str, Any] | None = None,
    ):
        if state not in _STATE_MESSAGES:
            raise ValueError(f"Unknown LiteLLM gateway state: {state!r}")
        reason = normalize_denial_reason(denial_reason)
        message = _STATE_MESSAGES[state]
        if reason:
            message = f"{message} [reason={reason}]"
        super().__init__(
            message,
            error_class=_STATE_ERROR_CLASSES[state],
            status_code=status_code,
            error_class_source=error_class_source,
            safe_detail=_safe_detail(state, reason, status_code, upstream_detail),
        )
        self.gateway_state = state
        self.denial_reason = reason
        # A content refusal's chat notice (``content_routing.notices``): names, counts and ids only.
        self.content_notice = dict(content_notice or {})

    def evidence(self) -> dict[str, object]:
        payload: dict[str, object] = {"gateway_state": self.gateway_state}
        if self.denial_reason:
            payload["denial_reason"] = self.denial_reason
        if self.status_code is not None:
            payload["status_code"] = int(self.status_code)
        return payload


# A transport exception type's runtime error class -> the gateway state that carries it.
_TRANSPORT_CLASS_STATES: dict[str, str] = {
    RUNTIME_ERROR_TIMEOUT: GATEWAY_STATE_TIMEOUT,
    RUNTIME_ERROR_UNREACHABLE: GATEWAY_STATE_UNREACHABLE,
    RUNTIME_ERROR_TRANSIENT: GATEWAY_STATE_UNAVAILABLE,
}


# Classified from the exception type; any other transport failure was never sent to a gateway that answered, so it stays
# gateway_unreachable.
def gateway_transport_error(exc: BaseException | None) -> LiteLLMGatewayError:
    state = _TRANSPORT_CLASS_STATES.get(transport_error_class(exc) or "")
    if state is None:
        return LiteLLMGatewayError(GATEWAY_STATE_UNREACHABLE)
    return LiteLLMGatewayError(state, error_class_source=CLASSIFICATION_SOURCE_EXCEPTION_TYPE)


def gateway_state_for_status(status_code: int) -> str:
    if 300 <= status_code < 400:
        # Redirects are never followed (the virtual key must not travel to a
        # host the endpoint allowlist never approved), so a 3xx is a pinned
        # endpoint that no longer serves this path: configuration, not content.
        return GATEWAY_STATE_CONFIGURATION_INVALID
    if status_code in (401, 403):
        return GATEWAY_STATE_UNAUTHORIZED
    if status_code == 408:
        return GATEWAY_STATE_TIMEOUT
    if status_code == 429:
        return GATEWAY_STATE_RATE_LIMITED
    if status_code >= 500:
        return GATEWAY_STATE_UNAVAILABLE
    return GATEWAY_STATE_REQUEST_REJECTED


__all__ = [
    "GATEWAY_STATES",
    "GATEWAY_STATE_ALIAS_DENIED",
    "GATEWAY_STATE_CAPABILITY_NOT_PROVEN",
    "GATEWAY_STATE_CONFIGURATION_INVALID",
    "GATEWAY_STATE_CONTEXT_PRESSURE",
    "GATEWAY_STATE_DATA_POLICY_DENIED",
    "GATEWAY_STATE_ENDPOINT_DENIED",
    "GATEWAY_STATE_FALLBACK_VIOLATION",
    "GATEWAY_STATE_RATE_LIMITED",
    "GATEWAY_STATE_REQUEST_REJECTED",
    "GATEWAY_STATE_RESPONSE_CONTRACT_VIOLATION",
    "GATEWAY_STATE_TIMEOUT",
    "GATEWAY_STATE_UNAUTHORIZED",
    "GATEWAY_STATE_UNAVAILABLE",
    "GATEWAY_STATE_UNREACHABLE",
    "GATEWAY_STATE_VIRTUAL_KEY_MISSING",
    "LiteLLMGatewayError",
    "gateway_state_for_status",
    "gateway_transport_error",
    "normalize_denial_reason",
]
