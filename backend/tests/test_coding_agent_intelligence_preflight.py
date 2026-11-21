"""Coding preflight planning: mode-driven bootstrap, repository analysis, code search and test suite reruns."""

from __future__ import annotations

from pathlib import Path

from app.agent.loops.request._loop_preflight import _plan_coding_preflight_tool_calls
from tests.coding_agent_intelligence_flow_support import _server_pipeline, _write_fixture  # noqa: F401


def test_plan_coding_preflight_bootstraps_empty_workspace_before_repository_analysis(tmp_path: Path):
    workspace = tmp_path / "empty-coding-workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    bootstrap_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Implement build_project_budget_warning_banner and include focused pytest tests.",
        workspace_root=str(workspace),
        allowed_tool_names={"bootstrap_workspace_repository", "analyze_workspace_repository", "code_search"},
        turn_tool_history=[],
    )

    assert bootstrap_calls is not None
    assert bootstrap_calls[0]["function"]["name"] == "bootstrap_workspace_repository"

    analyze_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Implement build_project_budget_warning_banner and include focused pytest tests.",
        workspace_root=str(workspace),
        allowed_tool_names={"bootstrap_workspace_repository", "analyze_workspace_repository", "code_search"},
        turn_tool_history=[
            {"tool_name": "bootstrap_workspace_repository", "result": {"bootstrap": {"status": "bootstrapped"}}}
        ],
    )

    assert analyze_calls is not None
    assert analyze_calls[0]["function"]["name"] == "analyze_workspace_repository"


def test_plan_coding_preflight_is_mode_driven_not_text_driven_by_default(tmp_path: Path):
    """Explicit-first: the coding mode plans preflight even without coding keywords."""
    workspace = tmp_path / "mode-driven-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)
    (workspace / ".git").mkdir(parents=True, exist_ok=True)

    planned = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Bitte kümmere dich um das Anliegen aus dem gestrigen Gespräch.",
        workspace_root=str(workspace),
        allowed_tool_names={"analyze_workspace_repository", "code_search"},
        turn_tool_history=[],
    )

    assert planned is not None
    assert planned[0]["function"]["name"] == "analyze_workspace_repository"


def test_plan_coding_preflight_ignores_coding_keywords_outside_coding_mode(tmp_path: Path):
    """A plain "fix this bug" prompt without an explicit coding mode plans no preflight tools."""
    workspace = tmp_path / "non-coding-mode-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)
    (workspace / ".git").mkdir(parents=True, exist_ok=True)

    planned = _plan_coding_preflight_tool_calls(
        capability_type="diagnosis",
        user_message="fix this bug",
        workspace_root=str(workspace),
        allowed_tool_names={"analyze_workspace_repository", "code_search"},
        turn_tool_history=[],
    )

    assert planned is None


def test_plan_coding_preflight_bootstraps_populated_non_git_workspace_before_repository_analysis(tmp_path: Path):
    workspace = tmp_path / "populated-coding-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)

    bootstrap_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Implement build_project_budget_warning_banner and include focused pytest tests.",
        workspace_root=str(workspace),
        allowed_tool_names={"bootstrap_workspace_repository", "analyze_workspace_repository", "code_search"},
        turn_tool_history=[],
    )

    assert bootstrap_calls is not None
    assert bootstrap_calls[0]["function"]["name"] == "bootstrap_workspace_repository"


def test_plan_coding_preflight_requests_code_search_after_bootstrap_and_repository_analysis(tmp_path: Path):
    workspace = tmp_path / "coding-preflight-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)

    code_search_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Implement build_project_budget_warning_banner and include focused pytest tests.",
        workspace_root=str(workspace),
        allowed_tool_names={"bootstrap_workspace_repository", "analyze_workspace_repository", "code_search"},
        turn_tool_history=[
            {"tool_name": "bootstrap_workspace_repository", "result": {"bootstrap": {"status": "bootstrapped"}}},
            {"tool_name": "bash", "result": {"exit_code": 0}},
            {"tool_name": "analyze_workspace_repository", "result": {"summary": {"files": 2}}},
        ],
    )

    assert code_search_calls is not None
    assert code_search_calls[0]["function"]["name"] == "code_search"
    assert "build_project_budget_warning_banner" in code_search_calls[0]["function"]["arguments"]


def test_plan_coding_preflight_reruns_test_suite_after_fixing_failed_tests(tmp_path: Path):
    workspace = tmp_path / "coding-verification-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)

    verification_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Implement build_project_budget_warning_banner and include focused pytest tests.",
        workspace_root=str(workspace),
        allowed_tool_names={"run_test_suite", "read_workspace_file", "edit_workspace_file"},
        turn_tool_history=[
            {
                "tool_name": "run_test_suite",
                "result": {"all_green": False, "passed": 7, "failed": 1, "errors": 0},
            },
            {"tool_name": "edit_workspace_file", "result": {"relative_path": "tests/test_budget.py"}},
            {"tool_name": "read_workspace_file", "result": {"relative_path": "tests/test_budget.py"}},
        ],
    )

    assert verification_calls is not None
    assert verification_calls[0]["function"]["name"] == "run_test_suite"


def test_plan_coding_preflight_does_not_repeat_failed_test_tool_attempt(tmp_path: Path):
    workspace = tmp_path / "coding-verification-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _write_fixture(workspace)

    verification_calls = _plan_coding_preflight_tool_calls(
        capability_type="change",
        user_message="Migrate a Java Spring Boot project and run Maven validation.",
        workspace_root=str(workspace),
        allowed_tool_names={"run_test_suite", "read_workspace_file", "edit_workspace_file"},
        turn_tool_history=[
            {"tool_name": "edit_workspace_file", "result": {"relative_path": "pom.xml"}},
            {"tool_name": "run_test_suite", "result": {"error": "Tool execution failed"}},
        ],
    )

    assert verification_calls is None
