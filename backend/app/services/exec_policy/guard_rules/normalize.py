"""Normalization of admin-defined custom tool guard rules and their condition trees."""

from __future__ import annotations

from typing import Any

from .constants import (
    CUSTOM_GUARD_CONDITION_OPERATORS,
    CUSTOM_TOOL_GUARD_ACTIONS,
    GUARD_SEVERITIES,
    MAX_CUSTOM_GUARD_CONDITION_DEPTH,
    MAX_CUSTOM_GUARD_CONDITIONS,
    MAX_CUSTOM_GUARD_FIELD_LENGTH,
    MAX_CUSTOM_GUARD_LIST_ITEMS,
    MAX_CUSTOM_GUARD_TEXT_LENGTH,
    MAX_CUSTOM_TOOL_GUARD_RULES,
)


def _normalized_short_text(value: Any, *, max_length: int = MAX_CUSTOM_GUARD_TEXT_LENGTH) -> str:
    return str(value or "").strip()[:max_length]


def _normalized_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.replace("\n", ",").split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item or "").strip() for item in value]
    else:
        raw_items = []
    normalized: list[str] = []
    for item in raw_items:
        if not item or item in normalized:
            continue
        normalized.append(item[:MAX_CUSTOM_GUARD_TEXT_LENGTH])
        if len(normalized) >= MAX_CUSTOM_GUARD_LIST_ITEMS:
            break
    return normalized


def _normalized_condition_values(value: Any) -> list[Any]:
    raw_values = value if isinstance(value, list) else [value]
    values: list[Any] = []
    for item in raw_values[:MAX_CUSTOM_GUARD_LIST_ITEMS]:
        if isinstance(item, str):
            values.append(_normalized_short_text(item))
        elif isinstance(item, bool | int | float) or item is None:
            values.append(item)
        else:
            values.append(_normalized_short_text(item))
    return values


def _condition_count(condition: dict[str, Any]) -> int:
    if "all" in condition:
        return sum(_condition_count(item) for item in condition.get("all") or [])
    if "any" in condition:
        return sum(_condition_count(item) for item in condition.get("any") or [])
    if "not" in condition:
        nested = condition.get("not")
        return _condition_count(nested) if isinstance(nested, dict) else 1
    return 1


def _normalize_custom_guard_condition(
    raw_condition: Any,
    *,
    depth: int = 0,
    validation_errors: list[str],
) -> dict[str, Any] | None:
    if raw_condition in (None, "", []):
        return None
    if not isinstance(raw_condition, dict):
        validation_errors.append("Condition must be an object.")
        return None
    if depth > MAX_CUSTOM_GUARD_CONDITION_DEPTH:
        validation_errors.append("Condition nesting is too deep.")
        return None
    group_keys = [key for key in ("all", "any", "not") if key in raw_condition]
    if group_keys:
        return _normalize_condition_group(
            raw_condition, group_keys, depth=depth, validation_errors=validation_errors
        )
    return _normalize_leaf_condition(raw_condition, validation_errors=validation_errors)


def _normalize_condition_group(
    raw_condition: dict[str, Any],
    group_keys: list[str],
    *,
    depth: int,
    validation_errors: list[str],
) -> dict[str, Any] | None:
    if len(group_keys) > 1:
        validation_errors.append("Condition groups must use only one of all, any, or not.")
        return None
    group_key = group_keys[0]
    if group_key == "not":
        nested = _normalize_custom_guard_condition(
            raw_condition.get("not"),
            depth=depth + 1,
            validation_errors=validation_errors,
        )
        return {"not": nested} if nested else None
    raw_items = raw_condition.get(group_key)
    if not isinstance(raw_items, list) or not raw_items:
        validation_errors.append(f"Condition group '{group_key}' must contain at least one condition.")
        return None
    normalized_items = [
        item
        for item in (
            _normalize_custom_guard_condition(
                raw_item,
                depth=depth + 1,
                validation_errors=validation_errors,
            )
            for raw_item in raw_items[:MAX_CUSTOM_GUARD_CONDITIONS]
        )
        if item is not None
    ]
    if not normalized_items:
        return None
    return {group_key: normalized_items}


def _normalize_leaf_condition(
    raw_condition: dict[str, Any],
    *,
    validation_errors: list[str],
) -> dict[str, Any] | None:
    field = _normalized_short_text(raw_condition.get("field"), max_length=MAX_CUSTOM_GUARD_FIELD_LENGTH)
    operator = str(raw_condition.get("operator") or "equals").strip().lower()
    if not field:
        validation_errors.append("Condition field is required.")
        return None
    if operator not in CUSTOM_GUARD_CONDITION_OPERATORS:
        validation_errors.append(f"Unsupported condition operator '{operator}'.")
        return None
    values = (
        []
        if operator in {"exists", "not_exists"}
        else _normalized_condition_values(raw_condition.get("values", raw_condition.get("value")))
    )
    if operator not in {"exists", "not_exists"} and not values:
        validation_errors.append(f"Condition operator '{operator}' requires a value.")
        return None
    value = values[0] if values else None
    return {
        "field": field,
        "operator": operator,
        "value": value,
        "values": values,
    }


def normalize_custom_tool_guard_rules(raw_rules: Any) -> list[dict[str, Any]]:
    raw_items = raw_rules if isinstance(raw_rules, list) else []
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_items[:MAX_CUSTOM_TOOL_GUARD_RULES]):
        if not isinstance(item, dict):
            continue
        guard_id = _normalized_short_text(item.get("id")) or f"custom_tool_guard_{index + 1}"
        guard_id = guard_id.replace(" ", "_")
        if guard_id in seen_ids:
            continue
        seen_ids.add(guard_id)
        action = str(item.get("action") or "block").strip().lower()
        severity = str(item.get("severity") or "medium").strip().lower()
        tool_names = _normalized_string_list(item.get("tool_names"))
        capability_types = [value.lower() for value in _normalized_string_list(item.get("capability_types"))]
        argument_key = _normalized_short_text(item.get("argument_key"), max_length=120)
        argument_contains = _normalized_short_text(item.get("argument_contains"))
        validation_errors: list[str] = []
        conditions = _normalize_custom_guard_condition(item.get("conditions"), validation_errors=validation_errors)
        if conditions and _condition_count(conditions) > MAX_CUSTOM_GUARD_CONDITIONS:
            validation_errors.append(
                f"Custom guard conditions are limited to {MAX_CUSTOM_GUARD_CONDITIONS} leaf checks."
            )
            conditions = None
        if not tool_names and not capability_types and not argument_key and not argument_contains and not conditions:
            validation_errors.append("At least one matcher is required.")
        normalized.append(
            {
                "id": guard_id,
                "label": _normalized_short_text(item.get("label")) or guard_id,
                "description": _normalized_short_text(item.get("description"), max_length=1000),
                "phase": "pre_tool_call",
                "category": "custom",
                "action": action if action in CUSTOM_TOOL_GUARD_ACTIONS else "block",
                "severity": severity if severity in GUARD_SEVERITIES else "medium",
                "enabled": bool(item.get("enabled", True)) and not validation_errors,
                "locked": False,
                "tool_names": tool_names,
                "capability_types": capability_types,
                "argument_key": argument_key,
                "argument_contains": argument_contains,
                "conditions": conditions,
                "validation_errors": validation_errors,
            }
        )
    return normalized

