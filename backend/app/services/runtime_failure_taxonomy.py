"""Runtime failure records for flow runs, classified by type and explicit codes only.

A failure record is stored on the orchestrator run and shown in flow traces and acceptance
states, so it carries fixed facts only: a closed category, a fixed summary sentence, the
exception class name and, for provider errors, the ``ProviderRuntimeError`` class and HTTP
status. The exception message is never read, neither to classify nor to store: a provider body,
a tool's error text or a subprocess line can carry hosts, tokens or credentialed URLs.

Classification precedence (every record says which source decided it, ``error_class_source``):

1. **explicit**: the caller's declared source (``validation_loop``, ``approval`` /
   ``human_review``), own typed errors (``FlowRuntimeLimitExceededError``,
   ``ToolPolicyDeniedError``, ``FlowInputContractError``, ``ToolResultFailedError`` with the tool
   result's own ``retryable`` flag) and exceptions carrying a ``runtime_error_class``
   (``ProviderRuntimeError``, whose declared source is kept).
2. **exception_type**: transport exception types (``transport_error_class``: timeouts,
   unreachable hosts, broken connections) mean the runtime is unavailable and a retry may pass.
3. **default**: everything else is a ``runtime_exception`` (or a ``tool_error`` on tool nodes).

There is no message-pattern path: a caller that only has text (the validation loop) declares
its source instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..agent.core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_DEFAULT,
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    CLASSIFICATION_SOURCE_EXPLICIT,
    PROVIDER_ERROR_CLASS_SOURCES,
    RUNTIME_ERROR_ALIAS_DENIED,
    RUNTIME_ERROR_CLASSES,
    RUNTIME_ERROR_CONTENT_POLICY_DENIED,
    RUNTIME_ERROR_DATA_POLICY_DENIED,
    RUNTIME_ERROR_PROVIDER_INIT,
    RUNTIME_ERROR_TIMEOUT,
    RUNTIME_ERROR_TRANSIENT,
    RUNTIME_ERROR_UNREACHABLE,
    transport_error_class,
)
from ..models.agent.orchestrator_agent import OrchestratorAgentRun
from ..time_utils import utc_now
from .error_facts import error_type
from .flow_runtime_governance import FlowRuntimeLimitExceededError
from .runtime_failure_errors import (
    _SAFE_CODE,
    FAILURE_SUMMARIES,
    ClassifiedFlowError,
    FlowInputContractError,
    ToolPolicyDeniedError,
    ToolResultFailedError,
)

FAILURE_SCHEMA_VERSION = "2.0"
FAILURE_KIND = "runtime_failure"
MAX_DETAIL_STRING_LENGTH = 800
MAX_DETAIL_ITEMS = 20

# Provider runtime classes that mean "not reachable right now"; a retry may pass.
_UNAVAILABLE_RUNTIME_CLASSES = frozenset({RUNTIME_ERROR_TIMEOUT, RUNTIME_ERROR_UNREACHABLE, RUNTIME_ERROR_TRANSIENT})
_POLICY_RUNTIME_CLASSES = frozenset(
    {RUNTIME_ERROR_ALIAS_DENIED, RUNTIME_ERROR_DATA_POLICY_DENIED, RUNTIME_ERROR_CONTENT_POLICY_DENIED}
)


@dataclass(frozen=True)
class RuntimeFailureContract:
    category: str
    severity: str
    retryable: bool
    required_action: str
    summary: str
    source: str
    error_class_source: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FAILURE_SCHEMA_VERSION,
            "kind": FAILURE_KIND,
            "category": self.category,
            "severity": self.severity,
            "retryable": self.retryable,
            "required_action": self.required_action,
            "summary": self.summary,
            "source": self.source,
            "error_class_source": self.error_class_source,
            "detail": self.detail,
            "created_at": utc_now().isoformat(),
        }


@dataclass(frozen=True)
class _Classification:
    category: str
    source: str
    severity: str = "error"
    retryable: bool = False
    action: str | None = None


def classify_runtime_failure(
    error: BaseException | None,
    *,
    source: str,
    node_id: str | None = None,
    node_type: str | None = None,
    required_action: str | None = None,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The stored failure record; ``error`` may be None when the caller declares its source."""
    exc = error if isinstance(error, BaseException) else None
    action = required_action or "inspect_trace"
    decided = _classify(exc, source=source, node_type=node_type, action=action)
    facts: dict[str, Any] = {"node_id": node_id, "node_type": node_type}
    if exc is not None:
        facts["error_type"] = error_type(exc)
        facts.update(_provider_facts(exc))
    if isinstance(exc, FlowRuntimeLimitExceededError):
        facts = {"code": _safe_code(exc.code), **exc.details, **facts}
    if isinstance(exc, ClassifiedFlowError):
        facts = {"code": _safe_code(exc.code), **facts}
    summary = FAILURE_SUMMARIES[decided.category]
    if exc is not None:
        summary = f"{summary} error_type={facts['error_type']}"
    return RuntimeFailureContract(
        category=decided.category,
        severity=decided.severity,
        retryable=decided.retryable,
        required_action=decided.action or action,
        summary=summary,
        source=source,
        error_class_source=decided.source,
        detail=_clean_detail({**(detail or {}), **facts}),
    ).to_dict()


def _classify(exc: BaseException | None, *, source: str, node_type: str | None, action: str) -> _Classification:
    explicit = CLASSIFICATION_SOURCE_EXPLICIT
    if isinstance(exc, FlowRuntimeLimitExceededError):
        return _Classification("budget_exceeded", explicit, action="adjust_runtime_limits")
    if isinstance(exc, ClassifiedFlowError):
        severity = "warning" if exc.category == "human_review_required" else "error"
        return _Classification(
            exc.category, explicit, severity=severity, retryable=exc.retryable, action=exc.required_action
        )
    if source == "validation_loop":
        return _Classification("validation_failed", explicit, retryable=action in {"repair", "rerun_validation"})
    if source == "approval" or action == "human_review":
        return _Classification("human_review_required", explicit, severity="warning", action="human_review")
    if isinstance(exc, ToolPolicyDeniedError):
        return _Classification("policy_blocked", explicit, severity="critical", action="review_policy")
    if isinstance(exc, FlowInputContractError):
        return _Classification("input_contract_error", explicit, action="fix_workflow_configuration")
    runtime_class, runtime_source = _runtime_class(exc)
    if runtime_class in _POLICY_RUNTIME_CLASSES:
        return _Classification("policy_blocked", runtime_source, severity="critical", action="review_policy")
    unavailable = runtime_class in _UNAVAILABLE_RUNTIME_CLASSES
    if isinstance(exc, ToolResultFailedError):
        return _tool_error(explicit, retryable=exc.retryable)
    if node_type in {"tool_step", "retrieval"}:
        return _tool_error(runtime_source, retryable=unavailable)
    if unavailable:
        return _Classification(
            "provider_or_runtime_unavailable", runtime_source, retryable=True, action="retry_runtime"
        )
    if runtime_class == RUNTIME_ERROR_PROVIDER_INIT:
        return _Classification(
            "provider_or_runtime_unavailable", runtime_source, action="fix_provider_configuration"
        )
    return _Classification("runtime_exception", runtime_source)


def _tool_error(source: str, *, retryable: bool) -> _Classification:
    return _Classification(
        "tool_error", source, retryable=retryable, action="retry_tool" if retryable else "inspect_tool_result"
    )


def _runtime_class(exc: BaseException | None) -> tuple[str | None, str]:
    """The provider runtime class from the explicit contract or the transport exception type."""
    if exc is None:
        return None, CLASSIFICATION_SOURCE_DEFAULT
    explicit_class = getattr(exc, "runtime_error_class", None)
    if isinstance(explicit_class, str) and explicit_class in RUNTIME_ERROR_CLASSES:
        declared = getattr(exc, "runtime_error_class_source", CLASSIFICATION_SOURCE_EXPLICIT)
        return explicit_class, declared if declared in PROVIDER_ERROR_CLASS_SOURCES else CLASSIFICATION_SOURCE_EXPLICIT
    transport_class = transport_error_class(exc)
    if transport_class:
        return transport_class, CLASSIFICATION_SOURCE_EXCEPTION_TYPE
    return None, CLASSIFICATION_SOURCE_DEFAULT


def _provider_facts(exc: BaseException) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    runtime_class, _ = _runtime_class(exc)
    if runtime_class:
        facts["runtime_error_class"] = runtime_class
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool) and 100 <= status_code <= 599:
        facts["http_status"] = status_code
    if isinstance(exc, ToolResultFailedError) and exc.tool_category:
        facts["tool_category"] = exc.tool_category
    return facts


def _safe_code(value: Any) -> str:
    text = str(value or "")
    return text if _SAFE_CODE.match(text) else "unexpected_error"


def record_runtime_failure(orchestrator_run: OrchestratorAgentRun, failure: dict[str, Any]) -> None:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = dict(policy.get("runtime") or {})
    runtime["failure"] = failure
    policy["runtime"] = runtime
    orchestrator_run.routing_policy_json = policy


def runtime_failure_state(orchestrator_run: OrchestratorAgentRun) -> dict[str, Any]:
    policy = dict(orchestrator_run.routing_policy_json or {})
    runtime = policy.get("runtime")
    failure = runtime.get("failure") if isinstance(runtime, dict) else None
    return dict(failure) if isinstance(failure, dict) else {}


def _clean_detail(value: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= MAX_DETAIL_ITEMS:
            cleaned["_truncated_keys"] = len(value) - MAX_DETAIL_ITEMS
            break
        if item is None or item == "":
            continue
        cleaned[str(key)] = _clean_value(item)
    return cleaned


def _clean_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _truncate(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value[:MAX_DETAIL_ITEMS]]
    if isinstance(value, dict):
        return _clean_detail(value)
    return _truncate(str(value))


def _truncate(value: str) -> str:
    if len(value) <= MAX_DETAIL_STRING_LENGTH:
        return value
    return f"{value[:MAX_DETAIL_STRING_LENGTH]}... [truncated {len(value) - MAX_DETAIL_STRING_LENGTH} chars]"


__all__ = [
    "classify_runtime_failure",
    "record_runtime_failure",
    "runtime_failure_state",
]
