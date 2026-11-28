"""Typed tool execution result metadata for registry dispatch boundaries."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.services.redaction_policy import redact_secret_text

from .definitions import get_tool_definition_metadata

TOOL_EXECUTION_RESULT_VERSION = "tool_execution.v1"
_MAX_ERROR_MESSAGE_CHARS = 500

@dataclass(frozen=True, slots=True)
class ToolOwnerIdentity:
    owner_type: str
    source: str
    connector: str | None
    risk: str
    required_config: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ToolExecutionError:
    tool_name: str
    category: str
    reason: str
    message: str
    owner: ToolOwnerIdentity
    policy: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TOOL_EXECUTION_RESULT_VERSION,
            "status": "error",
            "tool_name": self.tool_name,
            "category": self.category,
            "reason": self.reason,
            "message": self.message,
            "retryable": self.retryable,
            "policy": self.policy,
            "owner": self.owner.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    tool_name: str
    status: str
    owner: ToolOwnerIdentity
    category: str = "success"
    reason: str = "completed"
    message: str = ""
    policy: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": TOOL_EXECUTION_RESULT_VERSION,
            "status": self.status,
            "tool_name": self.tool_name,
            "category": self.category,
            "reason": self.reason,
            "message": self.message,
            "retryable": self.retryable,
            "policy": self.policy,
            "owner": self.owner.to_dict(),
        }


def safe_tool_error_message(value: Any, *, max_chars: int = _MAX_ERROR_MESSAGE_CHARS) -> str:
    return redact_secret_text(value, max_chars=max_chars)


def coerce_tool_result_payload(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return dict(result)
    data = getattr(result, "data", None)
    error = getattr(result, "error", None)
    if isinstance(data, dict):
        payload = dict(data)
    elif data is not None:
        payload = {"result": data}
    else:
        payload = {}
    if error is not None:
        payload["error"] = safe_tool_error_message(error)
    new_messages = getattr(result, "new_messages", None)
    if new_messages:
        payload["new_messages"] = new_messages
    return payload


def annotate_tool_result_payload(
    tool_name: str,
    result: Any,
    *,
    category: str | None = None,
    reason: str | None = None,
    policy: str | None = None,
    retryable: bool | None = None,
) -> dict[str, Any]:
    payload = coerce_tool_result_payload(result)
    if "tool_execution" in payload:
        return payload

    raw_error = payload.get("error")
    approval_required = bool(payload.get("approval_required")) or str(payload.get("approval_status") or "").strip() in {
        "pending",
        "unverifiable",
    }
    if raw_error is None and not approval_required and category is None:
        return payload

    safe_error = safe_tool_error_message(raw_error or reason or category or "Tool execution did not complete.")
    if raw_error is not None:
        payload["error"] = safe_error

    resolved_category = category or _infer_error_category(payload, safe_error)
    resolved_reason = safe_tool_error_message(reason or _infer_error_reason(payload, safe_error), max_chars=160)
    resolved_policy = policy or _infer_error_policy(payload)
    resolved_retryable = _infer_retryable(payload) if retryable is None else retryable
    owner = tool_owner_identity(tool_name, payload)
    metadata = ToolExecutionError(
        tool_name=str(tool_name or "").strip(),
        category=resolved_category,
        reason=resolved_reason,
        message=safe_error,
        policy=resolved_policy,
        retryable=resolved_retryable,
        owner=owner,
    )
    execution = metadata.to_dict()
    if approval_required:
        execution["status"] = "approval_required"
    payload["tool_execution"] = execution
    return payload


def tool_owner_identity(tool_name: str, payload: dict[str, Any] | None = None) -> ToolOwnerIdentity:
    payload = payload if isinstance(payload, dict) else {}
    policy_decision = payload.get("policy_decision") if isinstance(payload.get("policy_decision"), dict) else {}
    visibility_decision = (
        payload.get("visibility_decision") if isinstance(payload.get("visibility_decision"), dict) else {}
    )
    metadata = get_tool_definition_metadata(str(tool_name or "").strip())
    return ToolOwnerIdentity(
        owner_type=str(
            policy_decision.get("owner_type") or visibility_decision.get("owner_type") or metadata.owner_type
        ),
        source=str(policy_decision.get("source") or visibility_decision.get("source") or metadata.source),
        connector=(
            str(policy_decision.get("connector") or visibility_decision.get("connector") or metadata.connector).strip()
            or None
        ),
        risk=str(policy_decision.get("risk") or visibility_decision.get("risk") or metadata.risk),
        required_config=(
            str(
                policy_decision.get("required_config")
                or visibility_decision.get("required_config")
                or metadata.required_config
                or ""
            ).strip()
            or None
        ),
    )


def _infer_error_category(payload: dict[str, Any], safe_error: str) -> str:
    if payload.get("approval_required") or payload.get("blocked_by") == "tool_approval_gate":
        return "approval_required"
    explicit_category = str(payload.get("error_category") or "").strip()
    if explicit_category:
        return explicit_category
    if isinstance(payload.get("visibility_decision"), dict) or isinstance(payload.get("policy_decision"), dict):
        return "denied_by_policy"
    if payload.get("blocked_by") == "mcp_access_policy":
        return "denied_by_policy"
    if payload.get("circuit_breaker_state"):
        return "provider_failure"
    lowered = safe_error.lower()
    if lowered.startswith("unknown tool"):
        return "unknown_tool"
    if "requires a database-bound tool context" in lowered or "invalid mcp tool name format" in lowered:
        return "invalid_name" if "invalid mcp tool name format" in lowered else "validation_error"
    if lowered.startswith(("mcp tool execution failed", "database tool execution failed")):
        return "provider_failure"
    return "execution_failed"


def _infer_error_reason(payload: dict[str, Any], safe_error: str) -> str:
    policy_decision = payload.get("policy_decision") if isinstance(payload.get("policy_decision"), dict) else {}
    visibility_decision = (
        payload.get("visibility_decision") if isinstance(payload.get("visibility_decision"), dict) else {}
    )
    for candidate in (
        payload.get("reason"),
        policy_decision.get("reason"),
        visibility_decision.get("reason"),
        payload.get("blocked_by"),
        payload.get("circuit_breaker_state"),
        payload.get("approval_status"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return safe_error


def _infer_error_policy(payload: dict[str, Any]) -> str | None:
    policy_decision = payload.get("policy_decision") if isinstance(payload.get("policy_decision"), dict) else {}
    if policy_decision.get("policy"):
        return str(policy_decision["policy"])
    if payload.get("policy"):
        return str(payload["policy"])
    if payload.get("blocked_by") == "mcp_access_policy":
        return "mcp_access_policy"
    if payload.get("blocked_by") == "tool_approval_gate":
        return "tool_approval_gate"
    if payload.get("circuit_breaker_state"):
        return "circuit_breaker"
    return None


TOOL_CALL_AWAITING_APPROVAL = "awaiting_approval"


def tool_call_status(result: Any) -> str:
    if not isinstance(result, dict) or "error" not in result:
        return "success"
    pending = str(result.get("approval_status") or "").strip().lower() == "pending"
    if (result.get("approval_required") and pending) or result.get("status") == "awaiting_confirmation":
        return TOOL_CALL_AWAITING_APPROVAL
    return "error"


def _infer_retryable(payload: dict[str, Any]) -> bool:
    if payload.get("next_retry_at"):
        return True
    if payload.get("circuit_breaker_state"):
        return True
    return False


__all__ = [
    "TOOL_EXECUTION_RESULT_VERSION",
    "ToolExecutionError",
    "ToolExecutionResult",
    "ToolOwnerIdentity",
    "annotate_tool_result_payload",
    "coerce_tool_result_payload",
    "safe_tool_error_message",
    "TOOL_CALL_AWAITING_APPROVAL",
    "tool_call_status",
    "tool_owner_identity",
]
