"""Pure rule logic of connector watchers: payload normalization, matching, decisions, serialization."""

from __future__ import annotations

import fnmatch
from typing import Any

from ..models import (
    AuditLog,
    ConnectorWatcher,
    ConnectorWatcherEvent,
    ConnectorWatcherRule,
    ConnectorWatcherRuleDecision,
)
from .secure_work.jira_values import object_value

SUPPORTED_ACTIONS = {
    "audit_only",
    "notify",
    "update_state",
    "pause_active_work",
    "request_approval",
    "ask_agent_replan",
    "start_workflow",
}
SUPPORTED_OPERATORS = {"equals", "in", "contains", "exists", "matches"}
DECISION_PRIORITY = (
    "start_workflow",
    "ask_agent_replan",
    "request_approval",
    "pause_active_work",
    "update_state",
    "notify",
    "audit_only",
)

def serialize_connector_watcher_rule(row: ConnectorWatcherRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "description": row.description or "",
        "connector_name": row.connector_name,
        "connector_instance": row.connector_instance,
        "event_types": list(row.event_types_json or []),
        "conditions": dict(row.conditions_json or {}),
        "actions": _actions(row.actions_json),
        "enforcement": dict(row.enforcement_json or {}),
        "override_roles": list(row.override_roles_json or []),
        "rate_limit": dict(row.rate_limit_json or {}),
        "priority": row.priority,
        "status": row.status,
        "is_active": bool(row.is_active),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def serialize_connector_watcher_rule_decision(row: ConnectorWatcherRuleDecision) -> dict[str, Any]:
    return {
        "id": row.id,
        "rule_id": row.rule_id,
        "event_id": row.event_id,
        "watcher_id": row.watcher_id,
        "project_id": row.project_id,
        "decision": row.decision,
        "matched": bool(row.matched),
        "actions": list(row.actions_json or []),
        "reasons": list(row.reasons_json or []),
        "action_results": list(row.action_results_json or []),
        "audit": dict(row.audit_json or {}),
        "created_at": _iso(row.created_at),
    }

def _conditions(value: Any) -> dict[str, Any]:
    raw = object_value(value)
    conditions = raw.get("all") if isinstance(raw.get("all"), list) else []
    normalized = []
    for item in conditions:
        current = object_value(item)
        field = str(current.get("field") or "").strip()
        operator = str(current.get("operator") or "equals").strip().lower()
        if not field or operator not in SUPPORTED_OPERATORS:
            continue
        normalized.append({"field": field, "operator": operator, "value": current.get("value")})
    return {"all": normalized}


def _actions(value: Any) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else [value] if value else []
    actions: list[dict[str, Any]] = []
    for item in source:
        raw = {"type": item} if isinstance(item, str) else object_value(item)
        action_type = str(raw.get("type") or "").strip().lower()
        if action_type not in SUPPORTED_ACTIONS:
            continue
        actions.append({"type": action_type, "config": object_value(raw.get("config"))})
    return actions


def _rule_matches_context(rule: ConnectorWatcherRule, context: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if rule.connector_name and rule.connector_name != context.get("connector_name"):
        return False, [f"connector_name {context.get('connector_name')} did not match {rule.connector_name}"]
    if rule.connector_instance and rule.connector_instance != context.get("connector_instance"):
        return False, [
            f"connector_instance {context.get('connector_instance')} did not match {rule.connector_instance}"
        ]
    event_types = set(rule.event_types_json or [])
    if event_types and context.get("event_type") not in event_types:
        return False, [f"event_type {context.get('event_type')} did not match configured event types"]
    for condition in object_value(rule.conditions_json).get("all", []):
        matched, reason = _condition_matches(object_value(condition), context)
        reasons.append(reason)
        if not matched:
            return False, reasons
    return True, reasons or ["base rule scope matched"]


def _condition_matches(condition: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    field = str(condition.get("field") or "").strip()
    operator = str(condition.get("operator") or "equals").strip().lower()
    expected = condition.get("value")
    actual = _resolve_field(context, field)
    if operator == "exists":
        matched = actual not in (None, "")
    elif operator == "equals":
        matched = str(actual or "") == str(expected or "")
    elif operator == "in":
        matched = str(actual or "") in {str(item) for item in _list_value(expected)}
    elif operator == "contains":
        matched = str(expected or "") in str(actual or "")
    elif operator == "matches":
        matched = any(fnmatch.fnmatch(str(actual or ""), pattern) for pattern in _list_value(expected))
    else:
        matched = False
    return matched, f"{field} {operator} {expected!r}: {'matched' if matched else 'not matched'}"


def _event_context(watcher: ConnectorWatcher, event: ConnectorWatcherEvent) -> dict[str, Any]:
    raw_payload = dict(event.raw_payload_json or {})
    normalized = dict(event.normalized_json or {})
    scope = dict(event.scope_json or {})
    return {
        "connector_name": watcher.connector_name,
        "connector_instance": watcher.connector_instance,
        "provider_type": watcher.provider_type,
        "event_type": event.event_type,
        "external_id": event.external_id,
        "actor": event.actor,
        "scope": scope,
        "raw_payload": raw_payload,
        "normalized": normalized,
        "project": scope.get("project") or raw_payload.get("project"),
        "repository": scope.get("repository") or raw_payload.get("repository"),
        "branch": scope.get("branch") or raw_payload.get("branch"),
        "risk_level": raw_payload.get("risk_level") or normalized.get("risk_level"),
        "session_state": raw_payload.get("session_state") or normalized.get("session_state"),
    }


def _event_context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    scope = object_value(payload.get("scope"))
    return {
        "connector_name": payload.get("connector_name"),
        "connector_instance": payload.get("connector_instance"),
        "provider_type": payload.get("provider_type"),
        "event_type": payload.get("event_type"),
        "external_id": payload.get("external_id"),
        "actor": payload.get("actor"),
        "scope": scope,
        "raw_payload": object_value(payload.get("raw_payload")) or payload,
        "normalized": object_value(payload.get("normalized")),
        "project": scope.get("project") or payload.get("project"),
        "repository": scope.get("repository") or payload.get("repository"),
        "branch": scope.get("branch") or payload.get("branch"),
        "risk_level": payload.get("risk_level"),
        "session_state": payload.get("session_state"),
    }


def _resolve_field(context: dict[str, Any], field: str) -> Any:
    current: Any = context
    for part in field.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _decision(actions: list[dict[str, Any]]) -> str:
    action_types = {action["type"] for action in actions}
    return next((action_type for action_type in DECISION_PRIORITY if action_type in action_types), "audit_only")


def _action_result(action: dict[str, Any]) -> dict[str, Any]:
    action_type = action["type"]
    if action_type == "audit_only":
        return {"action": action_type, "status": "recorded", "effect": "audit"}
    return {"action": action_type, "status": "decision_recorded", "effect": "pending_runtime_handler"}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]


def _bounded_int(value: Any, *, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _audit(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> AuditLog:
    return AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
    )


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None
