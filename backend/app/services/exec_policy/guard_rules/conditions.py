"""Evaluation of custom guard condition trees against a tool call request."""

from __future__ import annotations

import fnmatch
import json
import math
from typing import Any

from .constants import MAX_CUSTOM_GUARD_ARGUMENT_TEXT_LENGTH


def _serialized_tool_args(tool_args: dict[str, Any]) -> str:
    try:
        text = json.dumps(tool_args or {}, sort_keys=True, default=str)
    except (TypeError, ValueError):
        text = str(tool_args or {})
    return text[:MAX_CUSTOM_GUARD_ARGUMENT_TEXT_LENGTH]


def _tool_guard_request(
    *,
    tool_name: str,
    tool_args: dict[str, Any],
    capability_type: str | None,
) -> dict[str, Any]:
    return {
        "tool": {
            "name": str(tool_name or ""),
            "capability_type": str(capability_type or ""),
        },
        "args": tool_args or {},
        "request": {
            "tool_name": str(tool_name or ""),
            "capability_type": str(capability_type or ""),
            "args": tool_args or {},
        },
    }


def _path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for raw_part in str(path or "").split("."):
        part = raw_part.strip()
        if not part:
            continue
        while "[" in part and part.endswith("]"):
            name, _, index_text = part[:-1].partition("[")
            if name:
                parts.append(name)
            try:
                parts.append(int(index_text))
            except ValueError:
                parts.append(index_text)
            part = ""
        if part:
            parts.append(part)
    return parts


def _field_value(data: Any, path: str) -> tuple[bool, Any]:
    current = data
    for part in _path_parts(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part < 0 or part >= len(current):
                return False, None
            current = current[part]
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return False, None
    return True, current


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _casefold(value: Any) -> str:
    return str(value if value is not None else "").casefold()


def _equals(left: Any, right: Any) -> bool:
    if isinstance(left, bool | int | float) and isinstance(right, bool | int | float):
        return left == right
    return _casefold(left) == _casefold(right)


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float) and math.isfinite(float(value)):
        return float(value)
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


_TEXT_OPERATORS = {"equals", "not_equals", "contains", "not_contains", "starts_with", "ends_with"}
_MEMBERSHIP_OPERATORS = {"in", "not_in", "any_in", "all_in", "any_not_in", "all_not_in"}
_NUMERIC_OPERATORS = {"greater_than", "greater_than_or_equals", "less_than", "less_than_or_equals"}


def _evaluate_leaf_condition(condition: dict[str, Any], request: dict[str, Any]) -> bool:
    exists, actual = _field_value(request, str(condition.get("field") or ""))
    operator = str(condition.get("operator") or "equals").strip().lower()
    values = list(condition.get("values") or [])
    expected = condition.get("value")
    if operator == "exists":
        return exists
    if operator == "not_exists":
        return not exists
    if not exists:
        return False
    if operator in _TEXT_OPERATORS:
        return _evaluate_text_operator(operator, actual, expected)
    if operator in _MEMBERSHIP_OPERATORS:
        return _evaluate_membership_operator(operator, actual, values)
    if operator in _NUMERIC_OPERATORS:
        return _evaluate_numeric_operator(operator, actual, expected)
    if operator == "matches_pattern":
        return fnmatch.fnmatchcase(_casefold(actual), _casefold(expected))
    return False


def _evaluate_text_operator(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "equals":
        return _equals(actual, expected)
    if operator == "not_equals":
        return not _equals(actual, expected)
    if operator == "contains":
        if isinstance(actual, list | tuple | set):
            return any(_equals(item, expected) for item in actual)
        return _casefold(expected) in _casefold(actual)
    if operator == "not_contains":
        if isinstance(actual, list | tuple | set):
            return all(not _equals(item, expected) for item in actual)
        return _casefold(expected) not in _casefold(actual)
    if operator == "starts_with":
        return _casefold(actual).startswith(_casefold(expected))
    return _casefold(actual).endswith(_casefold(expected))


def _evaluate_membership_operator(operator: str, actual: Any, values: list[Any]) -> bool:
    if operator == "in":
        return any(_equals(actual, item) for item in values)
    if operator == "not_in":
        return all(not _equals(actual, item) for item in values)
    actual_items = _as_list(actual)
    if operator == "any_in":
        return any(any(_equals(actual_item, expected_item) for expected_item in values) for actual_item in actual_items)
    if operator == "all_in":
        return bool(actual_items) and all(
            any(_equals(actual_item, expected_item) for expected_item in values) for actual_item in actual_items
        )
    if operator == "any_not_in":
        return any(
            all(not _equals(actual_item, expected_item) for expected_item in values) for actual_item in actual_items
        )
    return bool(actual_items) and all(
        all(not _equals(actual_item, expected_item) for expected_item in values) for actual_item in actual_items
    )


def _evaluate_numeric_operator(operator: str, actual: Any, expected: Any) -> bool:
    actual_number = _to_number(actual)
    expected_number = _to_number(expected)
    if actual_number is None or expected_number is None:
        return False
    if operator == "greater_than":
        return actual_number > expected_number
    if operator == "greater_than_or_equals":
        return actual_number >= expected_number
    if operator == "less_than":
        return actual_number < expected_number
    return actual_number <= expected_number


def _evaluate_custom_guard_condition(condition: dict[str, Any] | None, request: dict[str, Any]) -> bool:
    if not condition:
        return True
    if "all" in condition:
        return all(_evaluate_custom_guard_condition(item, request) for item in condition.get("all") or [])
    if "any" in condition:
        return any(_evaluate_custom_guard_condition(item, request) for item in condition.get("any") or [])
    if "not" in condition:
        nested = condition.get("not")
        return not _evaluate_custom_guard_condition(nested if isinstance(nested, dict) else None, request)
    return _evaluate_leaf_condition(condition, request)

