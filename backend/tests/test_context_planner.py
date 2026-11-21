import inspect

import pytest

from app.agent.core.context.context_planner import (
    build_context_section_decisions,
    classify_context_route,
    plan_turn_context,
)
from app.models import ScenarioProfile
from app.services.scenario_profile import apply_scenario_profile
from app.services.scenario_profile.service import _profile_matches


def _plan(**overrides):
    kwargs = {"project_id": "project-1", "agent_definition": None, "session_metadata": {}, "history_count": 0}
    return plan_turn_context(**{**kwargs, **overrides})


def test_the_prompt_is_not_a_planning_input():
    # The planner cannot read the wording, so two wordings cannot get two plans.
    assert "user_message" not in inspect.signature(plan_turn_context).parameters


@pytest.mark.parametrize(
    ("overrides", "rule_id", "tier", "variant"),
    [
        ({"capability_type": "admin"}, "admin_capability", "full", "admin"),
        ({"capability_type": "change"}, "change_or_continuation", "full", "full"),
        ({"is_change_mode": True}, "change_or_continuation", "full", "full"),
        ({"agent_definition": {"name": "Repo Worker"}}, "change_or_continuation", "full", "full"),
        ({"session_metadata": {"task_id": "t-1"}}, "change_or_continuation", "full", "full"),
        ({"session_metadata": {"parent_session_id": "s-0"}}, "change_or_continuation", "full", "full"),
        ({}, "contextual_request", "standard", "standard"),
        ({"project_id": None, "history_count": 3}, "contextual_request", "standard", "standard"),
        ({"project_id": None}, "default_standard", "standard", "standard"),
    ],
)
def test_explicit_inputs_select_the_rule(overrides, rule_id, tier, variant):
    plan = _plan(**overrides)

    assert plan.routing_rule_id == rule_id
    assert plan.route_reason == rule_id
    assert plan.tier == tier
    assert plan.system_prompt_variant == variant
    assert plan.tool_surface_source == "unresolved"


def test_full_rules_include_the_working_context():
    plan = _plan(capability_type="change", agent_definition={"name": "Repo Worker"}, history_count=12)

    assert plan.include_system_context and plan.include_skills
    assert plan.include_recent_history and plan.include_summary_context
    assert plan.include_agent_blueprint is True
    assert plan.recent_history_limit == 8
    assert plan.token_budget == 24000
    assert classify_context_route(plan) == "coding_change"


def test_history_depth_follows_the_conversation_size():
    short = _plan(history_count=3)
    long = _plan(history_count=9)
    summarized = _plan(session_metadata={"summary": "Earlier work"})

    assert short.include_recent_history and short.recent_history_limit == 6
    assert short.include_summary_context is False
    assert long.include_summary_context is True
    assert summarized.include_summary_context is True
    fresh = _plan(project_id=None)
    assert fresh.include_recent_history is False and fresh.recent_history_limit == 4


def test_project_override_retiers_or_disables_a_rule():
    retiered = _plan(project_config={"context_routing_policy": {"tier_overrides": {"contextual_request": "full"}}})
    assert retiered.tier == "full"
    assert retiered.routing_rule_source == "project_override"

    disabled = _plan(project_config={"context_routing_policy": {"disabled_rules": ["contextual_request"]}})
    assert disabled.routing_rule_id == "default_standard"


def test_section_decisions_name_the_tool_surface_source():
    plan = _plan()
    plan.include_tools = True
    plan.tool_surface_source = "governed_default"

    decisions = build_context_section_decisions(plan)

    assert decisions["tools"]["included"] is True
    assert decisions["tools"]["source"] == "tool_surface:governed_default"
    assert decisions["system_context"]["included"] is False


def test_scenario_profile_sizes_context_but_never_the_tool_surface():
    plan = _plan()
    profile = ScenarioProfile(
        id="scenario-1",
        owner_id="user-1",
        project_id="project-1",
        name="Custom Profile",
        planner_config={
            "include_skills": True,
            "recent_history_limit": 3,
            "include_tools": False,
            "tool_allowlist": ["get_current_time"],
            "blocked_tools": ["get_system_context"],
        },
        execution_config={"required_domains": ["jira", "bitbucket"], "enforce_domain_coverage": True},
        is_active=True,
    )

    updated = apply_scenario_profile(plan, profile)
    decisions = build_context_section_decisions(updated)

    assert updated.include_skills is True
    assert updated.recent_history_limit == 3
    assert updated.required_domains == ["jira", "bitbucket"]
    assert updated.enforce_domain_coverage is True
    # Tool fields are not read: the tool surface comes from the explicit sources only.
    assert updated.include_tools == plan.include_tools
    assert updated.tool_allowlist == plan.tool_allowlist
    assert updated.blocked_tools == plan.blocked_tools
    assert decisions["skills"]["source"] == "scenario_profile"
    assert decisions["skills"]["scenario_profile_name"] == "Custom Profile"


def test_scenario_profile_with_a_prompt_matcher_never_matches():
    plan = _plan()
    route_profile = ScenarioProfile(match_config={"route_reasons": ["contextual_request"]})
    keyword_profile = ScenarioProfile(match_config={"route_reasons": ["contextual_request"], "keywords": ["jira"]})
    pattern_profile = ScenarioProfile(match_config={"message_patterns": [".*"]})

    assert _profile_matches(route_profile, context_plan=plan) is True
    assert _profile_matches(keyword_profile, context_plan=plan) is False
    assert _profile_matches(pattern_profile, context_plan=plan) is False
