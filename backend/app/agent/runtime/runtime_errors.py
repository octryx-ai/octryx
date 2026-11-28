"""Explicit runtime error taxonomy for provider and runtime failures."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass

import httpx

try:  # botocore comes with the declared boto3; only the Bedrock provider raises its types.
    from botocore import exceptions as botocore_exceptions
except ImportError:  # pragma: no cover - boto3 is a base dependency
    botocore_exceptions = None

RUNTIME_ERROR_TIMEOUT = "timeout"
RUNTIME_ERROR_UNREACHABLE = "unreachable"
RUNTIME_ERROR_PROVIDER_INIT = "provider_init"
RUNTIME_ERROR_CONTEXT_PRESSURE = "context_pressure"
RUNTIME_ERROR_MALFORMED_RESPONSE = "malformed_response"
RUNTIME_ERROR_TRANSIENT = "transient"
RUNTIME_ERROR_PERMANENT = "permanent"
# Governed admission/contract states. They are only ever produced by an
# explicit ``ProviderRuntimeError``; no message pattern can reach them.
RUNTIME_ERROR_ALIAS_DENIED = "alias_denied"
# The workspace's server-owned data classification is not permitted for the
# target's declared data-policy class. Distinct from ``alias_denied`` so
# an operator can tell "this project may not use this alias" from "this data may
# not go to this model".
RUNTIME_ERROR_DATA_POLICY_DENIED = "data_policy_denied"
# A content policy refused the request for what it contains (the model-call boundary of every driver,
# ``services/content_security/model_call``). The content is the same for every target, so the chain stops.
RUNTIME_ERROR_CONTENT_POLICY_DENIED = "content_policy_denied"
# The Workspace's runtime assignment policy (``selected_only``) does not list the
# target. A zero-dispatch admission outcome like ``alias_denied``: the chain
# continues with the targets the Workspace allows.
RUNTIME_ERROR_RUNTIME_NOT_ALLOWED = "runtime_not_allowed"
RUNTIME_ERROR_CONTRACT_VIOLATION = "contract_violation"
RUNTIME_ERROR_FALLBACK_VIOLATION = "fallback_violation"

RUNTIME_ERROR_CLASSES = frozenset(
    {
        RUNTIME_ERROR_TIMEOUT,
        RUNTIME_ERROR_UNREACHABLE,
        RUNTIME_ERROR_PROVIDER_INIT,
        RUNTIME_ERROR_CONTEXT_PRESSURE,
        RUNTIME_ERROR_MALFORMED_RESPONSE,
        RUNTIME_ERROR_TRANSIENT,
        RUNTIME_ERROR_PERMANENT,
        RUNTIME_ERROR_ALIAS_DENIED,
        RUNTIME_ERROR_DATA_POLICY_DENIED,
        RUNTIME_ERROR_CONTENT_POLICY_DENIED,
        RUNTIME_ERROR_RUNTIME_NOT_ALLOWED,
        RUNTIME_ERROR_CONTRACT_VIOLATION,
        RUNTIME_ERROR_FALLBACK_VIOLATION,
    }
)

# Terminal by construction: both classes mean a runtime already produced (and
# therefore already billed) an answer that violates its pinned contract. A
# same-runtime retry or a cross-runtime fallback would buy a second billable
# answer for a deterministic defect and hide the violation behind a
# substituted model, so the chain stops instead.
#
# Deliberately NOT in this set: ``alias_denied`` and ``data_policy_denied``.
# Both are zero-dispatch admission outcomes, not served violations — the target
# is recorded as denied and the chain continues with the targets that *are*
# admitted, so a project-policy gap cannot hard-fail an entire runtime chain.
# For ``data_policy_denied`` that also bounds the claim: it keeps the data off
# the denied target, not off every target, because only the governed model
# gateway declares a per-alias data-policy class to compare against.
# ``content_policy_denied`` is terminal for a different reason: every runtime would refuse the same content again.
NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES = frozenset(
    {
        RUNTIME_ERROR_CONTENT_POLICY_DENIED,
        RUNTIME_ERROR_CONTRACT_VIOLATION,
        RUNTIME_ERROR_FALLBACK_VIOLATION,
    }
)

CLASSIFICATION_SOURCE_EXPLICIT = "explicit"
CLASSIFICATION_SOURCE_EXCEPTION_TYPE = "exception_type"
CLASSIFICATION_SOURCE_MESSAGE_PATTERN = "message_pattern"
CLASSIFICATION_SOURCE_DEFAULT = "default"
# The sources a ``ProviderRuntimeError`` may declare for its class: set by the
# provider itself, or translated from a typed transport exception.
PROVIDER_ERROR_CLASS_SOURCES = frozenset({CLASSIFICATION_SOURCE_EXPLICIT, CLASSIFICATION_SOURCE_EXCEPTION_TYPE})

_TRANSIENT_ERROR_TOKENS = (
    "429",
    "502",
    "503",
    "504",
    "rate limit",
    "temporar",
    "service unavailable",
    "overloaded",
)
_CONTEXT_PRESSURE_TOKENS = (
    "context window",
    "context length",
    "context limit",
    "too many tokens",
    "prompt is too long",
    "maximum context",
    "input too long",
    "token limit",
)
_MALFORMED_RESPONSE_TOKENS = (
    "invalid json",
    "non-object json",
    "missing choices",
    "missing message",
    "malformed",
    "invalid response payload",
    "invalid stream chunk",
    "invalid json stream chunks",
)

# Transport exception types, checked in this order: ``httpx.ConnectTimeout`` is a
# timeout before it is a connect failure, and botocore's timeouts subclass its
# connection errors.
def _botocore_types(*names: str) -> tuple[type[BaseException], ...]:
    if botocore_exceptions is None:
        return ()
    return tuple(getattr(botocore_exceptions, name) for name in names)


_TIMEOUT_EXCEPTION_TYPES = (
    TimeoutError,
    httpx.TimeoutException,
    *_botocore_types("ConnectTimeoutError", "ReadTimeoutError"),
)
_UNREACHABLE_EXCEPTION_TYPES = (
    ConnectionRefusedError,
    ConnectionAbortedError,
    socket.gaierror,
    httpx.ConnectError,
    httpx.ProxyError,
    *_botocore_types("EndpointConnectionError", "ProxyConnectionError"),
)
# The connection was established and then broke: the next request may succeed.
_TRANSIENT_EXCEPTION_TYPES = (
    ConnectionResetError,
    BrokenPipeError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.CloseError,
    *_botocore_types("ConnectionClosedError"),
)


class ProviderRuntimeError(Exception):
    def __init__(
        self,
        message: str,
        *,
        error_class: str,
        status_code: int | None = None,
        error_class_source: str = CLASSIFICATION_SOURCE_EXPLICIT,
        safe_detail: str = "",
    ):
        super().__init__(message)
        self.safe_detail = safe_detail
        if error_class not in RUNTIME_ERROR_CLASSES:
            raise ValueError(f"Unknown runtime error class: {error_class!r}")
        if error_class_source not in PROVIDER_ERROR_CLASS_SOURCES:
            raise ValueError(f"Unknown runtime error class source: {error_class_source!r}")
        self.runtime_error_class = error_class
        self.runtime_error_class_source = error_class_source
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class RuntimeErrorClassification:
    error_class: str
    source: str


def _message_matches(exc: Exception, tokens: tuple[str, ...]) -> bool:
    message = str(exc or "").strip().lower()
    return any(token in message for token in tokens)


def transport_error_class(exc: BaseException) -> str | None:
    if isinstance(exc, _TIMEOUT_EXCEPTION_TYPES):
        return RUNTIME_ERROR_TIMEOUT
    if isinstance(exc, _UNREACHABLE_EXCEPTION_TYPES):
        return RUNTIME_ERROR_UNREACHABLE
    if isinstance(exc, _TRANSIENT_EXCEPTION_TYPES):
        return RUNTIME_ERROR_TRANSIENT
    return None


def _declared_source(exc: Exception) -> str:
    source = getattr(exc, "runtime_error_class_source", CLASSIFICATION_SOURCE_EXPLICIT)
    return source if source in PROVIDER_ERROR_CLASS_SOURCES else CLASSIFICATION_SOURCE_EXPLICIT


def classify_runtime_error(exc: Exception, *, provider_init: bool = False) -> RuntimeErrorClassification:
    explicit_class = str(getattr(exc, "runtime_error_class", "") or "").strip()
    if explicit_class in RUNTIME_ERROR_CLASSES:
        return RuntimeErrorClassification(explicit_class, _declared_source(exc))
    transport_class = transport_error_class(exc)
    if transport_class in (RUNTIME_ERROR_TIMEOUT, RUNTIME_ERROR_UNREACHABLE):
        return RuntimeErrorClassification(transport_class, CLASSIFICATION_SOURCE_EXCEPTION_TYPE)
    if provider_init:
        return RuntimeErrorClassification(RUNTIME_ERROR_PROVIDER_INIT, CLASSIFICATION_SOURCE_DEFAULT)
    if isinstance(exc, json.JSONDecodeError):
        return RuntimeErrorClassification(RUNTIME_ERROR_MALFORMED_RESPONSE, CLASSIFICATION_SOURCE_EXCEPTION_TYPE)
    if transport_class == RUNTIME_ERROR_TRANSIENT:
        return RuntimeErrorClassification(RUNTIME_ERROR_TRANSIENT, CLASSIFICATION_SOURCE_EXCEPTION_TYPE)
    if _message_matches(exc, _CONTEXT_PRESSURE_TOKENS):
        return RuntimeErrorClassification(RUNTIME_ERROR_CONTEXT_PRESSURE, CLASSIFICATION_SOURCE_MESSAGE_PATTERN)
    if _message_matches(exc, _MALFORMED_RESPONSE_TOKENS):
        return RuntimeErrorClassification(RUNTIME_ERROR_MALFORMED_RESPONSE, CLASSIFICATION_SOURCE_MESSAGE_PATTERN)
    if _message_matches(exc, _TRANSIENT_ERROR_TOKENS):
        return RuntimeErrorClassification(RUNTIME_ERROR_TRANSIENT, CLASSIFICATION_SOURCE_MESSAGE_PATTERN)
    return RuntimeErrorClassification(RUNTIME_ERROR_PERMANENT, CLASSIFICATION_SOURCE_DEFAULT)


__all__ = [
    "CLASSIFICATION_SOURCE_DEFAULT",
    "CLASSIFICATION_SOURCE_EXCEPTION_TYPE",
    "CLASSIFICATION_SOURCE_EXPLICIT",
    "CLASSIFICATION_SOURCE_MESSAGE_PATTERN",
    "NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES",
    "PROVIDER_ERROR_CLASS_SOURCES",
    "RUNTIME_ERROR_ALIAS_DENIED",
    "RUNTIME_ERROR_CLASSES",
    "RUNTIME_ERROR_CONTEXT_PRESSURE",
    "RUNTIME_ERROR_CONTRACT_VIOLATION",
    "RUNTIME_ERROR_CONTENT_POLICY_DENIED",
    "RUNTIME_ERROR_DATA_POLICY_DENIED",
    "RUNTIME_ERROR_FALLBACK_VIOLATION",
    "RUNTIME_ERROR_MALFORMED_RESPONSE",
    "RUNTIME_ERROR_PERMANENT",
    "RUNTIME_ERROR_PROVIDER_INIT",
    "RUNTIME_ERROR_RUNTIME_NOT_ALLOWED",
    "RUNTIME_ERROR_TIMEOUT",
    "RUNTIME_ERROR_TRANSIENT",
    "RUNTIME_ERROR_UNREACHABLE",
    "ProviderRuntimeError",
    "RuntimeErrorClassification",
    "classify_runtime_error",
    "transport_error_class",
]
