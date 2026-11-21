from __future__ import annotations

from pathlib import Path

from app.agent.loops.request._loop_preflight import _plan_coding_preflight_tool_calls
from app.services.tool_surface_budget_policy import budget_tool_definitions_for_runtime
from app.tools.registry import get_tool_definitions


def test_budget_tool_definitions_for_copilot_change_keeps_coding_core_tools():
    tool_definitions = get_tool_definitions()

    budgeted = budget_tool_definitions_for_runtime(
        tool_definitions,
        runtimes=[{"provider_name": "copilot", "model": "gpt-4o"}],
        capability_type="change",
        coding_discipline="edit",
    )

    tool_names = {definition["function"]["name"] for definition in budgeted}

    assert len(tool_definitions) > 128
    assert len(budgeted) <= 96
    assert "write_workspace_file" in tool_names
    assert "code_search" in tool_names
    assert "run_test_suite" in tool_names
    assert "read_grafana_alert" not in tool_names


def test_budget_tool_definitions_for_bedrock_change_uses_focused_coding_surface():
    tool_definitions = get_tool_definitions()

    budgeted = budget_tool_definitions_for_runtime(
        tool_definitions,
        runtimes=[{"provider_name": "bedrock", "model": "amazon.nova-2-lite-v1:0"}],
        capability_type="change",
        coding_discipline="edit",
    )

    tool_names = {definition["function"]["name"] for definition in budgeted}

    assert len(tool_definitions) > 128
    assert len(budgeted) <= 96
    assert "prepare_bitbucket_repository" in tool_names
    assert "read_workspace_file" in tool_names
    assert "commit_and_push_repository_branch" in tool_names
    assert "build_pull_request_description" in tool_names
    assert "get_bitbucket_diff" in tool_names
    assert "bash" not in tool_names
    assert "read_bitbucket_file" not in tool_names
    assert "list_bitbucket_directory" not in tool_names
    assert "admin_create_user" not in tool_names
    assert "aws_topology_snapshot" not in tool_names


def test_budget_keeps_the_governed_default_surface_of_a_planning_turn():
    # Every non-coding turn reports the "planning" discipline; it is not a coding surface.
    tool_definitions = get_tool_definitions()

    uncapped = budget_tool_definitions_for_runtime(
        tool_definitions,
        runtimes=[{"provider_name": "bedrock", "model": "eu.anthropic.claude-sonnet-4-5"}],
        capability_type="diagnosis",
        coding_discipline="planning",
    )
    capped = budget_tool_definitions_for_runtime(
        tool_definitions,
        runtimes=[{"provider_name": "copilot", "model": "gpt-4o"}],
        capability_type="diagnosis",
        coding_discipline="planning",
    )

    assert uncapped == tool_definitions
    capped_names = {definition["function"]["name"] for definition in capped}
    assert len(capped) == 96
    assert {"select_workflow", "knowledge_search", "memory_recall", "search_jira_tickets"} <= capped_names


def test_plan_coding_preflight_forces_test_suite_after_first_workspace_mutation(tmp_path: Path):
    (tmp_path / ".git").mkdir()

    planned = _plan_coding_preflight_tool_calls(
        capability_type="coding",
        user_message="Implement build_project_budget_warning_banner with focused pytest tests.",
        workspace_root=str(tmp_path),
        allowed_tool_names={"run_test_suite", "write_workspace_file", "read_workspace_file"},
        turn_tool_history=[
            {
                "tool_name": "write_workspace_file",
                "result": {"relative_path": "tests/test_budget_banner.py"},
            }
        ],
    )

    assert planned is not None
    assert planned[0]["function"]["name"] == "run_test_suite"


def test_plan_coding_preflight_skips_empty_workspace_bootstrap_for_governed_work_plan(tmp_path: Path):
    planned = _plan_coding_preflight_tool_calls(
        capability_type="coding",
        user_message=(
            "You are Octryx's governed coding agent.\n"
            "Approved Work Plan\n"
            "Approved repositories and paths:\n"
            "- SHOP/aws-shop-infrastructure: terraform/base\n"
        ),
        workspace_root=str(tmp_path),
        allowed_tool_names={
            "bootstrap_workspace_repository",
            "analyze_workspace_repository",
            "code_search",
            "prepare_bitbucket_repository",
        },
        turn_tool_history=[],
    )

    assert planned is None
