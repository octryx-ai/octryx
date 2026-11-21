"""Forced wrap-up, hard stops and reminders after repeated tool errors, empty searches or a spent evidence budget."""

import pytest

from app.agent.loops.outcome._loop_post_tool import handle_post_tool_outcome
from app.agent.loops.outcome._loop_post_tool_inputs import PostToolInputs
from tests.loop_post_tool_support import _build_kwargs, _noop_async


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_forces_wrapup_after_repetitive_tool_errors() -> None:
    result = await handle_post_tool_outcome(PostToolInputs(
        **_build_kwargs(
            wrapup_forced=False,
            persist_traced_assistant_message=_noop_async,
        )
    ))

    assert result["action"] == "append_system_message"
    assert "Stop researching and conclude the current step now" in result["system_message"]
    assert result["current_step_iterations"] == 0
    assert result["current_step_wrapup_forced"] is True


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_stops_after_repeated_tool_errors_during_forced_wrapup() -> None:
    persisted: list[dict[str, object]] = []

    async def _capture_persisted_message(**kwargs):  # type: ignore[no-untyped-def]
        persisted.append(kwargs)
        return None

    result = await handle_post_tool_outcome(PostToolInputs(
        **_build_kwargs(
            wrapup_forced=True,
            persist_traced_assistant_message=_capture_persisted_message,
        )
    ))

    assert result["action"] == "return"
    assert "kept looping without reaching a conclusion" in result["yield_content"]
    assert len(persisted) == 1
    assert persisted[0]["content"] == result["yield_content"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_stops_after_repeated_empty_search_results() -> None:
    persisted: list[dict[str, object]] = []

    async def _capture_persisted_message(**kwargs):  # type: ignore[no-untyped-def]
        persisted.append(kwargs)
        return None

    result = await handle_post_tool_outcome(PostToolInputs(
        **_build_kwargs(
            wrapup_forced=False,
            persist_traced_assistant_message=_capture_persisted_message,
            stuck_loop_kind="repetitive_empty_search_loop",
            tool_results=[{"tool_name": "web_search", "result": {"count": 0, "items": []}}],
        )
    ))

    assert result["action"] == "return"
    assert "kept finding no search results" in result["yield_content"]
    assert len(persisted) == 1
    assert persisted[0]["content"] == result["yield_content"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_finishes_read_only_child_after_evidence_budget() -> None:
    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        current_user_message="Inspect source and test compatibility risks. Do not edit files.",
        tool_results=[
            {
                "tool_name": "grep_workspace",
                "result": {"matches": [{"file": "src/main/java/demo/Application.java"}]},
            }
        ],
        turn_tool_history=[
            {
                "tool_name": "read_workspace_file",
                "result": {"relative_path": f"src/main/java/demo/File{index}.java", "content": "class Demo {}"},
            }
            for index in range(11)
        ],
        active_steps=[],
    )
    kwargs["context_snapshot"] = {"sub_agent_depth": 1}
    kwargs["current_allowed_tool_names"] = {"analyze_workspace_repository", "grep_workspace", "read_workspace_file"}
    kwargs["current_step"] = None
    kwargs["current_step_index"] = 0
    kwargs["workflow_contract"] = {"workflow_id": "coding_change_tdd"}

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "return"
    assert "Read-only sub-agent evidence budget reached." in result["yield_content"]
    assert "No files were edited by this child." in result["yield_content"]


@pytest.mark.asyncio
async def test_handle_post_tool_outcome_reminds_governed_coding_before_hard_stop() -> None:
    kwargs = _build_kwargs(
        wrapup_forced=False,
        persist_traced_assistant_message=_noop_async,
        current_user_message="You are a governed coding agent. Execute this approved Work Plan.",
        tool_results=[{"tool_name": "read_workspace_file", "result": {"path": "terraform/base/irsa.tf"}}],
        turn_tool_history=[
            {"tool_name": "prepare_bitbucket_repository", "result": {"relative_path": "repo"}},
            *[
                {"tool_name": "read_workspace_file", "result": {"path": f"terraform/base/file-{index}.tf"}}
                for index in range(6)
            ],
        ],
        active_steps=[],
    )
    kwargs["current_step"] = None
    # The explicit governed signal: the approved verification contract on the workflow contract.
    kwargs["workflow_contract"] = {"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}}
    kwargs["runtime_settings"] = {"governed_coding_max_evidence_tools_without_delivery": 8}
    kwargs["current_allowed_tool_names"] = {
        "apply_patch_workspace",
        "ask_clarification",
        "read_workspace_file",
    }

    result = await handle_post_tool_outcome(PostToolInputs(**kwargs))

    assert result["action"] == "append_system_message"
    assert "The next step must be one of" in result["system_message"]
