"""Matching tool calls against custom guard rules and shaping the guard decision."""

from __future__ import annotations

from typing import Any

from .conditions import _evaluate_custom_guard_condition, _serialized_tool_args, _tool_guard_request
from .constants import BLOCKING_GUARD_ACTIONS, CUSTOM_TOOL_GUARD_RULES_KEY, GUARD_ACTIONS, GUARD_SEVERITIES
from .normalize import normalize_custom_tool_guard_rules


def _custom_tool_guard_matches(
    rule: dict[str, Any],
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
) -> bool:
    if not bool(rule.get("enabled", True)):
        return False
    tool_names = {str(value).strip().lower() for value in rule.get("tool_names") or [] if str(value).strip()}
    if tool_names and str(tool_name or "").strip().lower() not in tool_names:
        return False
    capability_types = {
        str(value).strip().lower() for value in rule.get("capability_types") or [] if str(value).strip()
    }
    if capability_types and str(capability_type or "").strip().lower() not in capability_types:
        return False
    argument_key = str(rule.get("argument_key") or "").strip()
    argument_contains = str(rule.get("argument_contains") or "").strip().lower()
    if argument_key:
        if argument_key not in (tool_args or {}):
            return False
        if argument_contains and argument_contains not in str((tool_args or {}).get(argument_key) or "").lower():
            return False
    elif argument_contains and argument_contains not in _serialized_tool_args(tool_args).lower():
        return False
    return _evaluate_custom_guard_condition(
        rule.get("conditions") if isinstance(rule.get("conditions"), dict) else None,
        _tool_guard_request(tool_name=tool_name, tool_args=tool_args, capability_type=capability_type),
    )


def custom_tool_guard_result(
    config: dict[str, Any] | None,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
) -> dict[str, Any] | None:
    for decision in custom_tool_guard_decisions(
        config,
        tool_name=tool_name,
        tool_args=tool_args,
        capability_type=capability_type,
    ):
        rule = decision["rule"]
        if str(rule.get("action") or "block").strip().lower() not in BLOCKING_GUARD_ACTIONS:
            continue
        return apply_agent_guard_metadata(
            {
                "error": (
                    f"Tool '{tool_name}' matched custom security guard '{rule['label']}'."
                ),
                "guardrail": str(rule["id"]),
                "reason": str(rule.get("description") or "Custom Exec Policy guard matched this tool call."),
                "tool_name": tool_name,
                "matched_guard": {
                    "id": rule["id"],
                    "label": rule["label"],
                    "tool_names": list(rule.get("tool_names") or []),
                    "capability_types": list(rule.get("capability_types") or []),
                    "argument_key": str(rule.get("argument_key") or ""),
                    "argument_contains": str(rule.get("argument_contains") or ""),
                    "conditions": rule.get("conditions"),
                },
            },
            rule,
        )
    return None


def custom_tool_guard_decisions(
    config: dict[str, Any] | None,
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    rules = normalize_custom_tool_guard_rules((config or {}).get(CUSTOM_TOOL_GUARD_RULES_KEY))
    for rule in rules:
        if not _custom_tool_guard_matches(
            rule,
            tool_name=tool_name,
            tool_args=tool_args,
            capability_type=capability_type,
        ):
            continue
        decisions.append(
            {
                "rule": rule,
                "guard_id": str(rule.get("id") or ""),
                "label": str(rule.get("label") or rule.get("id") or ""),
                "action": str(rule.get("action") or "block").strip().lower(),
                "severity": str(rule.get("severity") or "medium").strip().lower(),
                "reason": str(rule.get("description") or "Custom Exec Policy guard matched this tool call."),
                "tool_name": str(tool_name or ""),
                "capability_type": str(capability_type or ""),
                "matched_guard": {
                    "id": rule["id"],
                    "label": rule["label"],
                    "tool_names": list(rule.get("tool_names") or []),
                    "capability_types": list(rule.get("capability_types") or []),
                    "argument_key": str(rule.get("argument_key") or ""),
                    "argument_contains": str(rule.get("argument_contains") or ""),
                    "conditions": rule.get("conditions"),
                },
            }
        )
    return decisions

def apply_agent_guard_metadata(result: dict[str, Any], rule: dict[str, Any]) -> dict[str, Any]:
    guard_id = str(rule.get("id") or result.get("guardrail") or "").strip()
    action = str(rule.get("action") or "block").strip().lower()
    if action not in GUARD_ACTIONS:
        action = "block"
    severity = str(rule.get("severity") or "medium").strip().lower()
    if severity not in GUARD_SEVERITIES:
        severity = "medium"
    enriched = {
        **result,
        "guardrail": guard_id,
        "exec_policy_action": "review" if action == "review" else "deny",
        "exec_policy_reason": str(result.get("error") or result.get("suggested_next_step") or ""),
        "exec_policy_risk": severity,
    }
    if action == "review":
        enriched["approval_required"] = True
    return {
        **enriched,
        "guard_policy": {
            "id": guard_id,
            "label": str(rule.get("label") or guard_id),
            "phase": str(rule.get("phase") or "pre_tool_call"),
            "category": str(rule.get("category") or ""),
            "action": action,
            "severity": severity,
            "enabled": bool(rule.get("enabled")),
            "locked": bool(rule.get("locked")),
            "source": "exec_policy",
        },
    }

