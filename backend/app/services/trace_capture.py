"""How much of a trace payload is captured, per Workspace ``trace_capture`` config.

Debug and audit modes, errors, and sensitive tools keep the full (redacted) payload;
a standard success is compacted and the minimal mode keeps metadata only.
Redaction itself is ``trace_events.redact_trace_payload``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .trace_events import redact_trace_payload

TRACE_CAPTURE_PROJECT_CONFIG_KEY = "trace_capture"
TRACE_CAPTURE_MODES = {"minimal", "standard", "debug", "audit"}
DEFAULT_TRACE_CAPTURE_CONFIG = {
    "mode": "standard",
    "compact_max_string": 800,
    "compact_max_list_items": 8,
    "compact_max_dict_items": 24,
    "always_full_on_error": True,
    "always_full_on_sensitive_tools": True,
}


@dataclass(frozen=True)
class TraceCapturePolicy:
    mode: str = "standard"
    compact_max_string: int = 800
    compact_max_list_items: int = 8
    compact_max_dict_items: int = 24
    always_full_on_error: bool = True
    always_full_on_sensitive_tools: bool = True


@dataclass(frozen=True)
class TraceCaptureDecision:
    payload_mode: str
    reason: str
    policy: TraceCapturePolicy


def _coerce_trace_capture_policy(config: Mapping[str, Any] | None) -> TraceCapturePolicy:
    raw = config.get(TRACE_CAPTURE_PROJECT_CONFIG_KEY) if isinstance(config, Mapping) else None
    payload = raw if isinstance(raw, Mapping) else {}
    mode = str(payload.get("mode") or "standard").strip().lower()
    if mode not in TRACE_CAPTURE_MODES:
        mode = "standard"
    return TraceCapturePolicy(
        mode=mode,
        compact_max_string=max(120, min(4000, int(payload.get("compact_max_string") or 800))),
        compact_max_list_items=max(1, min(50, int(payload.get("compact_max_list_items") or 8))),
        compact_max_dict_items=max(4, min(100, int(payload.get("compact_max_dict_items") or 24))),
        always_full_on_error=bool(payload.get("always_full_on_error", True)),
        always_full_on_sensitive_tools=bool(payload.get("always_full_on_sensitive_tools", True)),
    )


def ensure_default_trace_capture_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    current = dict(config or {})
    trace_capture = current.get(TRACE_CAPTURE_PROJECT_CONFIG_KEY)
    if not isinstance(trace_capture, Mapping):
        current[TRACE_CAPTURE_PROJECT_CONFIG_KEY] = dict(DEFAULT_TRACE_CAPTURE_CONFIG)
        return current
    current[TRACE_CAPTURE_PROJECT_CONFIG_KEY] = {
        **DEFAULT_TRACE_CAPTURE_CONFIG,
        **dict(trace_capture),
    }
    return current


def _is_sensitive_tool_name(name: str) -> bool:
    lowered = name.lower()
    return any(part in lowered for part in ("approval", "secret", "token", "credential", "security", "permission"))


def _tool_trace_has_error(tool_trace: Any) -> bool:
    if not isinstance(tool_trace, list):
        return False
    for item in tool_trace:
        if not isinstance(item, Mapping):
            continue
        result = item.get("compact_result", item.get("result"))
        if isinstance(result, Mapping) and result.get("error"):
            return True
    return False


def _tool_trace_has_sensitive_tool(tool_trace: Any) -> bool:
    if not isinstance(tool_trace, list):
        return False
    return any(
        isinstance(item, Mapping) and _is_sensitive_tool_name(str(item.get("tool_name") or ""))
        for item in tool_trace
    )


def decide_trace_capture(
    policy: TraceCapturePolicy,
    *,
    root_status: str,
    tool_trace: Any,
) -> TraceCaptureDecision:
    if policy.mode in {"debug", "audit"}:
        return TraceCaptureDecision(payload_mode="full", reason=f"{policy.mode}_mode", policy=policy)
    if policy.always_full_on_error and (root_status == "error" or _tool_trace_has_error(tool_trace)):
        return TraceCaptureDecision(payload_mode="full", reason="error", policy=policy)
    if policy.always_full_on_sensitive_tools and _tool_trace_has_sensitive_tool(tool_trace):
        return TraceCaptureDecision(payload_mode="full", reason="sensitive_tool", policy=policy)
    if policy.mode == "minimal":
        return TraceCaptureDecision(payload_mode="metadata_only", reason="minimal_mode", policy=policy)
    return TraceCaptureDecision(payload_mode="compact", reason="standard_success", policy=policy)


def _compact_policy_payload(value: Any, policy: TraceCapturePolicy, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, str):
        if len(value) <= policy.compact_max_string:
            return value
        return value[: policy.compact_max_string] + "\n...[truncated]"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        items = value[: policy.compact_max_list_items]
        compacted = [_compact_policy_payload(item, policy, depth=depth + 1) for item in items]
        if len(value) > policy.compact_max_list_items:
            compacted.append(f"...[{len(value) - policy.compact_max_list_items} more items truncated]")
        return compacted
    if isinstance(value, Mapping):
        compacted: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= policy.compact_max_dict_items:
                compacted["__truncated__"] = f"{len(value) - policy.compact_max_dict_items} more keys truncated"
                break
            compacted[str(key)] = _compact_policy_payload(item, policy, depth=depth + 1)
        return compacted
    return str(value)


def apply_trace_capture_to_payload(value: Any, decision: TraceCaptureDecision) -> Any:
    redacted_value = redact_trace_payload(value)
    if decision.payload_mode == "metadata_only":
        return {"capture": "metadata_only", "reason": decision.reason}
    if decision.payload_mode == "compact":
        return _compact_policy_payload(redacted_value, decision.policy)
    return redacted_value
