"""The turn's tool surface comes from a closed precedence of explicit sources.

Selected definition, selected workflow, agent definition, Workspace tool policy, governed
default: the first source that declares a surface wins, and every level offers tools. The
context planner never decides whether a turn has tools.
"""

from __future__ import annotations

import pytest

from app.agent.core.context.context_planner import plan_turn_context
from app.agent.core.context.tool_families import COMMON_READ_ONLY_TOOLS
from app.agent.core.context.turn_tool_surface import (
    agent_definition_tool_allowlist,
    resolve_turn_tool_surface,
    resolve_workflow_tool_surface,
)
from app.services.session.turn_tool_surface_record import TOOL_SURFACE_SOURCES


def _plain_plan():
    return plan_turn_context(project_id="p1", agent_definition=None, session_metadata={}, history_count=0)


def _definition_resolution(allowlist):
    return {
        "source": "db",
        "status": "matched",
        "workflow_id": "jira_release_status",
        "tool_policy": {"allowlist": allowlist},
    }


_BLUEPRINT = {
    "name": "Release Checker",
    "steps": [
        {"name": "Look up", "isEnabled": True, "allowedTools": ["list_jira_versions"]},
        {"name": "Report", "isEnabled": True, "allowedTools": ["search_jira_tickets"]},
        {"name": "Disabled", "isEnabled": False},
    ],
}


def _surface(**overrides):
    kwargs = {
        "capability_type": "diagnosis",
        "workflow_id": None,
        "workflow_contract": None,
        "routing_resolution": None,
        "agent_definition": None,
        "project_config": {},
        **overrides,
    }
    return resolve_turn_tool_surface(_plain_plan(), **kwargs)


def test_the_planner_leaves_the_tool_surface_unresolved():
    plan = _plain_plan()
    assert plan.tool_surface_source == "unresolved"
    assert plan.tool_allowlist is None


@pytest.mark.parametrize(
    ("overrides", "source", "expected_tools"),
    [
        (
            {
                "routing_resolution": _definition_resolution(["jira_release_status"]),
                "workflow_contract": {"allowed_tools": ["list_jira_versions"]},
                "agent_definition": _BLUEPRINT,
                "project_config": {"tool_policy": {"allowlist": ["web_search"]}},
            },
            "selected_definition",
            {"jira_release_status", "list_jira_versions"},
        ),
        (
            {
                "workflow_id": "knowledge_request",
                "agent_definition": _BLUEPRINT,
                "project_config": {"tool_policy": {"allowlist": ["web_search"]}},
            },
            "selected_workflow",
            {"knowledge_search", "knowledge_read"},
        ),
        (
            {"agent_definition": _BLUEPRINT, "project_config": {"tool_policy": {"allowlist": ["web_search"]}}},
            "agent_definition",
            {"list_jira_versions", "search_jira_tickets"},
        ),
        ({"project_config": {"tool_policy": {"allowlist": ["web_search"]}}}, "workspace_policy", None),
        ({}, "governed_default", {"knowledge_search", "memory_recall"}),
    ],
)
def test_each_precedence_level_records_its_source(overrides, source, expected_tools):
    plan = _surface(**overrides)

    assert plan.tool_surface_source == source
    assert plan.tool_surface_source in TOOL_SURFACE_SOURCES
    assert plan.include_tools is True
    # Only the governed default names a versioned set.
    assert plan.tool_surface_set == ("diagnosis.v10" if source == "governed_default" else "")
    if expected_tools is None:
        # The capability catalog, filtered by visibility and the Workspace policy at build time.
        assert plan.tool_allowlist is None
    else:
        assert expected_tools <= set(plan.tool_allowlist)
        # The workflow-selection meta tool survives every narrowed surface.
        assert {"get_current_time", "select_workflow"} <= set(plan.tool_allowlist)


def test_a_selected_definition_keeps_its_w18_surface():
    plan = _surface(
        routing_resolution=_definition_resolution(["jira_release_status", "list_jira_versions"]),
        workflow_contract={"allowed_tools": ["search_jira_tickets"]},
    )
    assert set(plan.tool_allowlist) == {
        "jira_release_status",
        "list_jira_versions",
        "search_jira_tickets",
        *COMMON_READ_ONLY_TOOLS,
    }


def test_a_pattern_only_definition_still_turns_tools_on():
    resolution = {"source": "db", "status": "matched", "tool_policy": {"allow_patterns": ["jira_*"]}}
    plan = _surface(routing_resolution=resolution)
    assert plan.tool_surface_source == "selected_definition"
    assert set(plan.tool_allowlist) == set(COMMON_READ_ONLY_TOOLS)


def test_an_unmatched_resolution_is_not_a_selected_definition():
    resolution = {**_definition_resolution(["jira_release_status"]), "status": "unmatched"}
    assert _surface(routing_resolution=resolution).tool_surface_source == "governed_default"


def test_a_blueprint_with_an_undeclared_step_does_not_bound_the_surface():
    blueprint = {"steps": [*_BLUEPRINT["steps"], {"name": "Free", "isEnabled": True}]}
    assert agent_definition_tool_allowlist(blueprint) is None
    assert _surface(agent_definition=blueprint).tool_surface_source == "governed_default"
    assert agent_definition_tool_allowlist({"name": "No steps"}) is None


def test_a_deny_only_workspace_policy_does_not_define_the_surface():
    config = {"tool_policy": {"denylist": ["bash"]}}
    assert _surface(project_config=config).tool_surface_source == "governed_default"


def test_resolve_by_workflow_id():
    surface = resolve_workflow_tool_surface(workflow_id="knowledge_request", workflow_contract={})
    # Governed evidence only: the ledger.
    assert surface and "knowledge_search" in surface
    assert not {"knowledge_get", "list_project_knowledge"} & set(surface)
    # forbidden skill tools stripped from the knowledge surface
    assert "skill_search" not in surface


def test_resolve_prefers_contract_allowed_tools():
    surface = resolve_workflow_tool_surface(
        workflow_id="knowledge_request",
        workflow_contract={"allowed_tools": ["custom_tool_a", "custom_tool_b"]},
    )
    assert "custom_tool_a" in surface and "custom_tool_b" in surface


def test_resolve_returns_none_for_a_turn_without_a_selected_workflow():
    assert resolve_workflow_tool_surface(workflow_id="", workflow_contract={}) is None
    assert resolve_workflow_tool_surface(workflow_id=None, workflow_contract=None) is None
