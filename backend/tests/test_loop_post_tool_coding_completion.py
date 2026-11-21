"""Synthesized direct and TDD coding completions after green tests or a Maven verify."""

import pytest

from app.agent.loops.outcome._loop_post_tool import handle_post_tool_outcome
from app.agent.loops.outcome._loop_post_tool_inputs import PostToolInputs
from tests.loop_post_tool_support import _build_kwargs, _noop_async


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_synthesizes_direct_coding_completion_after_green_tests() -> None:
    synthesized: list[dict[str, object]] = []

    async def _capture_synthesized_message(**kwargs):  # type: ignore[no-untyped-def]
        synthesized.append(kwargs)
        return None

    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        tool_results=[
            {
                "tool_name": "run_test_suite",
                "result": {
                    "all_green": True,
                    "command": ["/usr/bin/python3", "-m", "pytest", ".", "-q"],
                    "passed": 7,
                    "failed": 0,
                    "errors": 0,
                },
            }
        ],
        turn_tool_history=[
            {"tool_name": "write_workspace_file", "result": {"relative_path": "budget.py"}},
            {"tool_name": "write_workspace_file", "result": {"relative_path": "tests/test_budget.py"}},
            {
                "tool_name": "run_test_suite",
                "result": {
                    "all_green": True,
                    "command": ["/usr/bin/python3", "-m", "pytest", ".", "-q"],
                    "passed": 7,
                    "failed": 0,
                    "errors": 0,
                },
            },
        ],
        active_steps=[],
    )
    kwargs["current_step"] = None
    kwargs["current_step_index"] = 0
    kwargs["persist_synthesized_tool_assistant"] = _capture_synthesized_message
    kwargs["workflow_contract"] = None

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "return"
    assert "Implemented the requested coding change" in result["yield_content"]
    assert "budget.py" in result["yield_content"]
    assert "tests/test_budget.py" in result["yield_content"]
    assert "Passed: 7" in result["yield_content"]
    assert len(synthesized) == 1
    assert synthesized[0]["content"] == result["yield_content"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_synthesizes_direct_coding_completion_after_maven_verify() -> None:
    synthesized: list[dict[str, object]] = []

    async def _capture_synthesized_message(**kwargs):  # type: ignore[no-untyped-def]
        synthesized.append(kwargs)
        return None

    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        current_user_message="Aktualisiere das Jenkinsfile und validiere die Änderung mit Maven.",
        tool_results=[
            {
                "tool_name": "run_cli_command",
                "result": {
                    "command": "mvn -q clean verify",
                    "effective_command": "mvn -q clean verify",
                    "exit_code": 0,
                },
            }
        ],
        turn_tool_history=[
            {"tool_name": "edit_workspace_file", "result": {"relative_path": "Jenkinsfile"}},
            {
                "tool_name": "run_openrewrite_recipe",
                "result": {
                    "dry_run": True,
                    "exit_code": 0,
                    "changed": False,
                },
            },
            {
                "tool_name": "run_cli_command",
                "result": {
                    "command": "mvn -q clean verify",
                    "effective_command": "mvn -q clean verify",
                    "exit_code": 0,
                },
            },
        ],
        active_steps=[],
    )
    kwargs["current_step"] = None
    kwargs["current_step_index"] = 0
    kwargs["persist_synthesized_tool_assistant"] = _capture_synthesized_message
    kwargs["workflow_contract"] = None

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "return"
    assert "Implemented the requested coding change" in result["yield_content"]
    assert "Jenkinsfile" in result["yield_content"]
    assert "`mvn -q clean verify` exited with code 0" in result["yield_content"]
    assert len(synthesized) == 1
    assert synthesized[0]["content"] == result["yield_content"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_synthesizes_tdd_coding_completion_after_green_tests() -> None:
    synthesized: list[dict[str, object]] = []

    async def _capture_synthesized_message(**kwargs):  # type: ignore[no-untyped-def]
        synthesized.append(kwargs)
        return None

    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        tool_results=[
            {
                "tool_name": "run_test_suite",
                "result": {
                    "all_green": True,
                    "command": ["/usr/bin/python3", "-m", "pytest", ".", "-q"],
                    "passed": 7,
                    "failed": 0,
                    "errors": 0,
                },
            }
        ],
        turn_tool_history=[
            {"tool_name": "write_workspace_file", "result": {"relative_path": "project_budget.py"}},
            {"tool_name": "write_workspace_file", "result": {"relative_path": "test_project_budget.py"}},
            {
                "tool_name": "run_test_suite",
                "result": {
                    "all_green": True,
                    "command": ["/usr/bin/python3", "-m", "pytest", ".", "-q"],
                    "passed": 7,
                    "failed": 0,
                    "errors": 0,
                },
            },
        ],
        active_steps=[{"name": "Implement And Verify Change"}],
        workflow_contract={"workflow_id": "coding_change_tdd"},
    )
    kwargs["current_step"] = {"name": "Implement And Verify Change", "stepType": "tdd_cycle"}
    kwargs["tdd_cycle_state"] = {"phase_index": 1, "phases": [{"name": "write_tests"}, {"name": "make_green"}]}
    kwargs["persist_synthesized_tool_assistant"] = _capture_synthesized_message
    kwargs["is_tdd_cycle_step"] = lambda step: True
    kwargs["is_tdd_cycle_complete"] = lambda state: True

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "return"
    assert "Implemented the requested coding change" in result["yield_content"]
    assert "project_budget.py" in result["yield_content"]
    assert "test_project_budget.py" in result["yield_content"]
    assert len(synthesized) == 1
    assert synthesized[0]["content"] == result["yield_content"]
