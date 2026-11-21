"""The routing intent of a turn, read from its stored workflow routing resolution."""

from __future__ import annotations

from typing import Any

_SUPPORTED_ROUTING_INTENTS = {
    "coding",
    "documentation",
    "knowledge",
    "admin_control",
    "operations",
    "diagnosis",
    "support_request",
}
_WORKFLOW_ID_ROUTING_INTENT_MAP = {
    "knowledge_request": "knowledge",
}


def resolve_workflow_intent_from_resolution(
    *,
    resolution: dict[str, Any] | None = None,
    fallback_route_reason: str | None = None,
) -> tuple[str, str]:
    normalized_route_reason = str(fallback_route_reason or "").strip().lower()
    payload = resolution or {}
    if not isinstance(payload, dict):
        return "", ""
    source = str(payload.get("source") or "").strip().lower()
    status = str(payload.get("status") or "").strip().lower()
    if source != "db" or status != "matched":
        if normalized_route_reason:
            if "knowledge" in normalized_route_reason:
                return "knowledge", f"route_reason:{normalized_route_reason}"
            if "documentation" in normalized_route_reason:
                return "documentation", f"route_reason:{normalized_route_reason}"
            if "admin" in normalized_route_reason:
                return "admin_control", f"route_reason:{normalized_route_reason}"
            if "operations" in normalized_route_reason or "diagnosis" in normalized_route_reason:
                return (
                    "operations" if "operations" in normalized_route_reason else "diagnosis",
                    f"route_reason:{normalized_route_reason}",
                )
        return "", ""

    workflow_contract = dict(payload.get("workflow_contract") or {})
    for hint_key in ("routing_intent", "intent", "intent_hint"):
        candidate = str(workflow_contract.get(hint_key) or "").strip().lower()
        if candidate in _SUPPORTED_ROUTING_INTENTS:
            return candidate, f"routing_policy:{hint_key}"
    workflow_id = str(workflow_contract.get("workflow_id") or payload.get("workflow_id") or "").strip().lower()
    workflow_class = str(workflow_contract.get("workflow_class") or payload.get("workflow_class") or "").strip().lower()
    if workflow_id in _WORKFLOW_ID_ROUTING_INTENT_MAP:
        return _WORKFLOW_ID_ROUTING_INTENT_MAP[workflow_id], f"routing_policy:{workflow_id}"
    if workflow_class in _WORKFLOW_ID_ROUTING_INTENT_MAP:
        return _WORKFLOW_ID_ROUTING_INTENT_MAP[workflow_class], f"routing_policy:{workflow_class}"
    if normalized_route_reason:
        if "knowledge" in normalized_route_reason:
            return "knowledge", f"route_reason:{normalized_route_reason}"
        if "documentation" in normalized_route_reason:
            return "documentation", f"route_reason:{normalized_route_reason}"
        if "admin" in normalized_route_reason:
            return "admin_control", f"route_reason:{normalized_route_reason}"
        if "operations" in normalized_route_reason:
            return "operations", f"route_reason:{normalized_route_reason}"
    return "", ""
