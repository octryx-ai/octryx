"""Tests for the explicit context routing policy table and its override contract."""

import dataclasses

from app.services.context_routing_policy import (
    DEFAULT_CONTEXT_ROUTING_RULES,
    ContextRoutingSignals,
    evaluate_context_routing,
)


def _decide(signals: ContextRoutingSignals, project_config: dict | None = None):
    return evaluate_context_routing(signals, project_config)


def test_the_rule_table_has_only_explicit_rules():
    assert [(rule.rule_id, rule.tier) for rule in DEFAULT_CONTEXT_ROUTING_RULES] == [
        ("admin_capability", "full"),
        ("change_or_continuation", "full"),
        ("contextual_request", "standard"),
        ("default_standard", "standard"),
    ]
    # Every signal is an explicit input of the turn; none is derived from the prompt.
    assert {field.name for field in dataclasses.fields(ContextRoutingSignals)} == {
        "is_admin_agent",
        "is_change_agent",
        "has_task_context",
        "has_parent_context",
        "has_project",
        "history_count",
        "has_summary",
    }


def test_default_table_decisions():
    cases = [
        (ContextRoutingSignals(is_admin_agent=True, is_change_agent=True), "admin_capability", "full"),
        (ContextRoutingSignals(is_change_agent=True), "change_or_continuation", "full"),
        (ContextRoutingSignals(has_task_context=True), "change_or_continuation", "full"),
        (ContextRoutingSignals(has_parent_context=True), "change_or_continuation", "full"),
        (ContextRoutingSignals(has_project=True), "contextual_request", "standard"),
        (ContextRoutingSignals(history_count=2), "contextual_request", "standard"),
        (ContextRoutingSignals(has_summary=True), "contextual_request", "standard"),
        (ContextRoutingSignals(), "default_standard", "standard"),
    ]
    for signals, expected_rule_id, expected_tier in cases:
        decision = _decide(signals)
        assert decision.rule_id == expected_rule_id, signals
        assert decision.tier == expected_tier, signals
        assert decision.route_reason == expected_rule_id
        assert decision.source == "default_policy"


def test_tier_override_is_audited_as_project_override():
    decision = _decide(
        ContextRoutingSignals(has_project=True),
        {"context_routing_policy": {"tier_overrides": {"contextual_request": "full"}}},
    )
    assert decision.rule_id == "contextual_request"
    assert decision.tier == "full"
    assert decision.source == "project_override"


def test_disabled_rule_falls_through_and_fallback_cannot_be_disabled():
    contextual = ContextRoutingSignals(has_project=True)
    assert (
        _decide(contextual, {"context_routing_policy": {"disabled_rules": ["contextual_request"]}}).rule_id
        == "default_standard"
    )
    fallback = _decide(ContextRoutingSignals(), {"context_routing_policy": {"disabled_rules": ["default_standard"]}})
    assert fallback.rule_id == "default_standard"
    assert fallback.source == "default_policy"


def test_deleted_keyword_rules_and_invalid_overrides_are_ignored():
    project_config = {
        "context_routing_policy": {
            # The retired re-enable key and the deleted keyword rules have no effect.
            "enabled_rules": ["knowledge_lookup", "trivial_new_thread", "admin_control"],
            "tier_overrides": {"knowledge_lookup": "full", "contextual_request": "not_a_tier"},
            "disabled_rules": ["summary_aggregation", 42],
        }
    }

    decision = _decide(ContextRoutingSignals(has_project=True), project_config)

    assert decision.rule_id == "contextual_request"
    assert decision.tier == "standard"
    assert decision.source == "default_policy"
