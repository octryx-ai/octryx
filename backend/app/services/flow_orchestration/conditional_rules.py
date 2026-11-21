"""Shape validation of authored router conditions.

The evaluator (``dag.conditions._condition_matches`` / ``_operator_condition_matches``) treats every
malformed comparison as "no match". So a rule with an unknown operator, a blank field or a
non-list ``in`` operand would silently fall through to the default branch. This module decides, before
anything is evaluated, whether a saved condition is one the evaluator can actually decide.

It is used by two callers with the same rules:
- the v2 validator, which refuses saving or validating such a flow;
- the runtime, which fails the router node before it picks a branch, so stored snapshots fail
  visibly instead of choosing the default.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ..runtime_failure_errors import ClassifiedFlowError

ROUTER_RULE_INVALID = "router_rule_invalid"
ROUTER_CONDITION_INVALID = "router_condition_invalid"

# Operator spellings the evaluator understands, by canonical meaning (dag.conditions._operator_condition_matches).
_EQUALITY = frozenset({"equals", "eq", "==", "not_equals", "neq", "!="})
_CONTAINS = frozenset({"contains", "not_contains"})
_LIST = frozenset({"in", "not_in"})
_NUMBER = frozenset({"gt", "gte", "lt", "lte"})
_BOOLEAN = frozenset({"exists", "truthy"})
SUPPORTED_OPERATORS = _EQUALITY | _CONTAINS | _LIST | _NUMBER | _BOOLEAN


# Plain-English explanation per closed problem code, for validation messages (never runtime records).
CONDITION_PROBLEM_TEXT = {
    "rules_not_a_list": "the rules must be a list.",
    "rule_not_an_object": "this rule is not an object with a condition and a branch.",
    "condition_not_an_object": "the condition must be an object with a field, a comparison and a value.",
    "missing_field": "choose the value to check (field is missing or blank).",
    "unknown_operator": "this comparison is not supported.",
    "missing_comparison": "choose a comparison for the field.",
    "missing_value": "this comparison needs a value.",
    "list_value_required": "this comparison needs a list of values.",
    "number_value_required": "this comparison needs a finite number (not yes/no, NaN or infinity).",
    "boolean_value_required": "this comparison needs yes or no (true/false).",
}


@dataclass(frozen=True, slots=True)
class ConditionIssue:
    """One problem: where (``rules[0].when``, ``connection router->b``) and a closed problem code."""

    location: str
    problem: str


class RouterRuleInvalidError(ClassifiedFlowError):
    """A router rule or custom connection condition cannot be decided; no branch is chosen."""

    def __init__(self, code: str) -> None:
        super().__init__(code, category="input_contract_error", required_action="fix_workflow_configuration")


def _operand_problem(operator: str, value: Any, *, present: bool) -> str | None:
    if operator in _BOOLEAN:
        return None if present and isinstance(value, bool) else "boolean_value_required"
    if not present:
        return "missing_value"
    if operator in _LIST:
        return None if isinstance(value, list) else "list_value_required"
    if operator in _NUMBER:
        return None if _finite_number(value) else "number_value_required"
    # equals/not_equals and contains/not_contains take any present JSON value, ``null`` and structured
    # values included: membership in a list of objects or lists is legitimate and evaluated.
    return None


def _finite_number(value: Any) -> bool:
    """A threshold the evaluator compares meaningfully: a finite number or finite numeric string.

    ``float()`` alone also accepts booleans (``True`` is 1.0), ``"nan"`` (every comparison false)
    and ``"inf"``/``"1e999"``/huge integers (an always-or-never threshold, or an overflow error).
    Those are configuration mistakes and are refused.
    """
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def comparison_problem(condition: Any) -> str | None:
    """The problem of one non-empty comparison object, or ``None`` when the evaluator can decide it."""
    if not isinstance(condition, dict):
        return "condition_not_an_object"
    field = condition.get("field")
    if not isinstance(field, str) or not field.strip():
        return "missing_field"
    raw_operator = condition.get("operator")
    if raw_operator is not None and not isinstance(raw_operator, str):
        return "unknown_operator"
    operator = (raw_operator or "").strip().lower()
    if not operator:
        return "missing_comparison"
    if operator not in SUPPORTED_OPERATORS:
        return "unknown_operator"
    return _operand_problem(operator, condition.get("value"), present="value" in condition)


def router_rule_issues(config: Any) -> list[ConditionIssue]:
    """Problems of a router's ``routes``. A missing, null or ``{}`` ``when`` is an explicit always-match rule."""
    if not isinstance(config, dict) or config.get("routes") is None:
        return []
    routes = config["routes"]
    if not isinstance(routes, list):
        return [ConditionIssue("routes", "rules_not_a_list")]
    issues: list[ConditionIssue] = []
    for index, rule in enumerate(routes):
        if not isinstance(rule, dict):
            issues.append(ConditionIssue(f"rules[{index}]", "rule_not_an_object"))
            continue
        when = rule.get("when")
        if when is None or when == {}:
            # Missing, null or {}: the explicit always-match rule. Other falsy values (false, 0, "",
            # []) are not objects; they are refused rather than silently matching the first rule.
            continue
        problem = comparison_problem(when)
        if problem:
            issues.append(ConditionIssue(f"rules[{index}].when", problem))
    return issues


def connection_condition_problem(condition: Any) -> str | None:
    """Only a non-empty custom predicate (a dict without ``route``) is checked; branch names and fallbacks are not."""
    if not condition or not isinstance(condition, dict) or "route" in condition:
        return None
    return comparison_problem(condition)


def ensure_router_rules_valid(config: Any) -> None:
    if router_rule_issues(config):
        raise RouterRuleInvalidError(ROUTER_RULE_INVALID)


def ensure_connection_conditions_valid(conditions: Iterable[Any]) -> None:
    if any(connection_condition_problem(condition) for condition in conditions):
        raise RouterRuleInvalidError(ROUTER_CONDITION_INVALID)


__all__ = [
    "CONDITION_PROBLEM_TEXT",
    "ROUTER_CONDITION_INVALID",
    "ROUTER_RULE_INVALID",
    "SUPPORTED_OPERATORS",
    "ConditionIssue",
    "RouterRuleInvalidError",
    "comparison_problem",
    "connection_condition_problem",
    "ensure_connection_conditions_valid",
    "ensure_router_rules_valid",
    "router_rule_issues",
]
