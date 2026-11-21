"""Condition evaluation for router rules and router edges."""

from __future__ import annotations

from typing import Any

from .paths import _read_path


def _condition_matches(condition: dict[str, Any], input_snapshot: dict[str, Any]) -> bool:
    if not condition:
        return True
    field = str(condition.get("field") or "").strip()
    if not field:
        return False
    actual = _read_path(input_snapshot, field)
    operator = str(condition.get("operator") or "").strip().lower()
    if not operator:
        return False
    return _operator_condition_matches(actual, operator=operator, expected=condition.get("value"))


def _router_edge_condition_matches(condition: Any, *, route: str, router_output: dict[str, Any]) -> bool:
    if isinstance(condition, str):
        return condition in {route, f"route:{route}"}
    if not isinstance(condition, dict):
        return False
    if "route" in condition:
        return str(condition.get("route") or "") == route
    context = {**router_output}
    nested_input = router_output.get("input")
    if isinstance(nested_input, dict):
        context = {**nested_input, **router_output}
    return _condition_matches(condition, context)


def _operator_condition_matches(actual: Any, *, operator: str, expected: Any) -> bool:
    if operator in {"equals", "eq", "=="}:
        return actual == expected
    if operator in {"not_equals", "neq", "!="}:
        return actual != expected
    if operator == "exists":
        return (actual is not None) is bool(expected)
    if operator == "in" and isinstance(expected, list):
        return actual in expected
    if operator == "not_in" and isinstance(expected, list):
        return actual not in expected
    if operator == "contains":
        return _contains_value(actual, expected)
    if operator == "not_contains":
        return not _contains_value(actual, expected)
    if operator in {"gt", "gte", "lt", "lte"}:
        return _compare_number(actual, expected, operator=operator)
    if operator == "truthy":
        return bool(actual) is bool(expected)
    return False


def _contains_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, str):
        return str(expected) in actual
    if isinstance(actual, list | tuple | set):
        return expected in actual
    if isinstance(actual, dict):
        return expected in actual or expected in actual.values()
    return False


def _compare_number(actual: Any, expected: Any, *, operator: str) -> bool:
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    return False
