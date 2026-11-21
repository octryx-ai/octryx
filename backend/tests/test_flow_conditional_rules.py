"""Authored router conditions are validated instead of silently falling to the default branch.

Valid operators, aliases, numeric strings, unconditional rules, first match and the default keep
their behaviour. A comparison names its operator in ``operator``; a key-form comparison
(``{"field": ..., "operator": "equals", "value": ...}``) has no comparison and is refused. Malformed shapes are refused
when a flow is validated or saved. In a saved snapshot they fail the router node before it picks a
branch, and nothing downstream runs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.models.runtime.flow_definition import FlowDefinition
from app.services.flow_orchestration.conditional_rules import (
    comparison_problem,
    connection_condition_problem,
    router_rule_issues,
)
from app.services.flow_v2_validation import validate_flow_definition_v2
from tests.flow_conditional_rules_support import _router_flow


def _codes(definition: dict) -> list[str]:
    return [error["code"] for error in validate_flow_definition_v2(definition)["errors"]]


# --- comparison shapes ----------------------------------------------------------------


@pytest.mark.parametrize(
    "condition",
    [
        {"field": "kind", "operator": "equals", "value": "a"},
        {"field": "kind", "operator": " EQ ", "value": "a"},
        {"field": "kind", "operator": "==", "value": "a"},
        {"field": "kind", "operator": "!=", "value": None},  # explicit null comparison
        {"field": "kind", "operator": "neq", "value": 1},
        {"field": "kind", "operator": "in", "value": ["a", "b"]},
        {"field": "kind", "operator": "not_in", "value": []},
        {"field": "kind", "operator": "contains", "value": "x"},
        {"field": "tags", "operator": "contains", "value": {"k": "v"}},  # structured operands stay valid
        {"field": "pairs", "operator": "not_contains", "value": ["a", 1]},
        {"field": "kind", "operator": "contains", "value": None},
        {"field": "amount", "operator": "gt", "value": 10},
        {"field": "amount", "operator": "lte", "value": "5"},  # finite numeric strings stay valid
        {"field": "amount", "operator": "gte", "value": " -2.5e3 "},
        {"field": "kind", "operator": "exists", "value": True},
        {"field": "kind", "operator": "truthy", "value": False},
        {"field": "$input.kind", "operator": "equals", "value": "a"},
    ],
)
def test_valid_comparisons_and_aliases_are_accepted(condition):
    assert comparison_problem(condition) is None


@pytest.mark.parametrize(
    ("condition", "problem"),
    [
        ({"field": "kind", "operator": "matches", "value": "a"}, "unknown_operator"),
        ({"field": "kind", "operator": 5, "value": "a"}, "unknown_operator"),
        ({"field": "", "operator": "equals", "value": "a"}, "missing_field"),
        ({"field": "  ", "operator": "equals", "value": "a"}, "missing_field"),
        ({"operator": "equals", "value": "a"}, "missing_field"),
        ({"field": 3, "operator": "equals", "value": "a"}, "missing_field"),
        ({"field": "kind"}, "missing_comparison"),
        # The key form names no operator: it is not a comparison.
        ({"field": "$input.kind", "equals": "a"}, "missing_comparison"),
        ({"field": "kind", "in": ["a"]}, "missing_comparison"),
        ({"field": "amount", "gte": 3}, "missing_comparison"),
        ({"field": "kind", "exists": False}, "missing_comparison"),
        ({"field": "kind", "operator": "", "equals": "a"}, "missing_comparison"),
        ({"field": "kind", "operator": "equals"}, "missing_value"),
        ({"field": "kind", "operator": "in", "value": "a"}, "list_value_required"),
        ({"field": "kind", "operator": "not_in", "value": "a"}, "list_value_required"),
        ({"field": "kind", "operator": "contains"}, "missing_value"),
        ({"field": "amount", "operator": "gt", "value": "ten"}, "number_value_required"),
        ({"field": "amount", "operator": "lt", "value": None}, "number_value_required"),
        ({"field": "amount", "operator": "gt", "value": True}, "number_value_required"),
        ({"field": "amount", "operator": "gt", "value": float("nan")}, "number_value_required"),
        ({"field": "amount", "operator": "lt", "value": "NaN"}, "number_value_required"),
        ({"field": "amount", "operator": "gte", "value": float("inf")}, "number_value_required"),
        ({"field": "amount", "operator": "lte", "value": "-Infinity"}, "number_value_required"),
        ({"field": "amount", "operator": "gt", "value": "1e999"}, "number_value_required"),
        ({"field": "amount", "operator": "gt", "value": 10**400}, "number_value_required"),
        ({"field": "kind", "operator": "exists", "value": "false"}, "boolean_value_required"),
        ({"field": "kind", "operator": "truthy", "value": 1}, "boolean_value_required"),
        ("kind == a", "condition_not_an_object"),
    ],
)
def test_malformed_comparisons_name_their_problem(condition, problem):
    assert comparison_problem(condition) == problem


def test_rules_keep_unconditional_rules_and_refuse_broken_rule_lists():
    for when in (None, {}):
        assert router_rule_issues({"routes": [{"route": "a", "when": when}]}) == []
    assert router_rule_issues({"routes": [{"route": "a"}]}) == []
    # Falsy non-objects are malformed, not "always": they must not silently pick the first rule.
    for when in (False, 0, "", [], "x", 5):
        issues = router_rule_issues({"routes": [{"route": "a", "when": when}]})
        assert [(issue.location, issue.problem) for issue in issues] == [("rules[0].when", "condition_not_an_object")]
    assert router_rule_issues({"default_route": "b"}) == []
    assert [issue.problem for issue in router_rule_issues({"routes": "a"})] == ["rules_not_a_list"]
    issues = router_rule_issues({"routes": ["a", {"route": "b", "when": {"field": "k", "operator": "nope"}}]})
    assert [(issue.location, issue.problem) for issue in issues] == [
        ("rules[0]", "rule_not_an_object"),
        ("rules[1].when", "unknown_operator"),
    ]


def test_only_custom_connection_predicates_are_checked():
    for condition in (None, "", {}, "route:a", "a", {"route": "a"}, {"field": "route", "operator": "equals", "value": "a"}):
        assert connection_condition_problem(condition) is None
    assert connection_condition_problem({"field": "route", "equals": "a"}) == "missing_comparison"
    assert connection_condition_problem({"field": "route", "operator": "like", "value": "a"}) == "unknown_operator"


def test_the_validator_refuses_malformed_rules_and_predicates_and_names_them():
    report = validate_flow_definition_v2(
        _router_flow([{"route": "a", "when": {"field": "kind", "operator": "matches", "value": "a"}}])
    )
    rule_errors = [error for error in report["errors"] if error["code"] == "router_rule_invalid"]
    assert rule_errors == [
        {"code": "router_rule_invalid", "message": "router.rules[0].when: this comparison is not supported."}
    ]
    predicate = {"field": "route", "operator": "in", "value": "a"}
    assert "router_condition_invalid" in _codes(
        _router_flow([{"route": "a", "when": {"field": "kind", "operator": "equals", "value": "a"}}],
                     connections=[("a", predicate), ("b", "route:b")])
    )


def test_the_validator_refuses_falsy_when_and_non_finite_thresholds():
    for when in (False, 0, "", [], {"field": "amount", "operator": "gt", "value": "inf"},
                 {"field": "amount", "operator": "gt", "value": True}):
        assert "router_rule_invalid" in _codes(_router_flow([{"route": "a", "when": when}])), when


def test_the_validator_accepts_valid_aliases_and_unconditional_rules():
    for rules in (
        [{"route": "a", "when": {"field": "kind", "operator": "==", "value": "a"}}],
        [{"route": "a", "when": {"field": "amount", "operator": "gt", "value": "5"}}],
        [{"route": "a", "when": {"field": "tags", "operator": "contains", "value": {"k": "v"}}}],
        [{"route": "a", "when": {}}],
        [{"route": "a", "when": None}],
    ):
        codes = _codes(_router_flow(rules))
        assert "router_rule_invalid" not in codes and "router_condition_invalid" not in codes, rules


@pytest.mark.asyncio
async def test_the_api_reports_and_refuses_a_malformed_rule(client, auth_headers, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    definition = _router_flow([{"route": "a", "when": {"field": "", "operator": "equals", "value": "a"}}])

    validated = await client.post("/api/v1/flows/validate", headers=auth_headers, json={"definition": definition})
    assert validated.status_code == 200
    assert validated.json()["valid"] is False
    assert "router_rule_invalid" in {error["code"] for error in validated.json()["errors"]}

    created = await client.post(
        "/api/v1/flows",
        headers=auth_headers,
        json={"project_id": project.id, "key": "malformed-rule-flow", "name": "Malformed rule", "definition": definition},
    )
    assert created.status_code >= 400
    stored = (await db.execute(select(FlowDefinition).where(FlowDefinition.key == "malformed-rule-flow"))).scalars()
    assert stored.all() == []


def test_the_evaluator_does_not_match_a_key_form_comparison():
    from app.services.flow_orchestration.dag.conditions import _condition_matches

    assert _condition_matches({"field": "kind", "operator": "equals", "value": "a"}, {"kind": "a"}) is True
    for condition in ({"field": "kind", "equals": "a"}, {"field": "kind", "operator": "", "equals": "a"},
                      {"field": "amount", "gt": 1}):
        assert _condition_matches(condition, {"kind": "a", "amount": 7}) is False
