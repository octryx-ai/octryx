"""Response guards prioritizing governed coding delivery."""

from __future__ import annotations

import pytest

from app.agent.core.guards.response_guards import (
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
    is_transitional_tool_call_preamble,
    looks_like_step_completion_summary,
)
from app.agent.loops.response._loop_response_guard_inputs import ResponseGuardInputs
from app.agent.loops.response._loop_response_guards import handle_response_guards
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist, _noop_trace


@pytest.mark.asyncio
async def test_response_guard_prioritizes_governed_coding_delivery_over_summary_domains() -> None:
    messages: list[dict[str, str]] = []
    current_turn = "You are Octryx's governed coding agent. Execute this approved Work Plan."
    turn_tool_history = [
        {"tool_name": "prepare_bitbucket_repository", "result": {"relative_path": "repo"}},
        {"tool_name": "read_workspace_file", "result": {"relative_path": "terraform/base/removed.txt"}},
        {"tool_name": "read_workspace_file", "result": {"relative_path": "terraform/base/memorydb-disable.txt"}},
    ]

    outcome = await handle_response_guards(ResponseGuardInputs(
        db=_DummyDB(),
        session_id="session-governed-coding-summary-order",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[{"role": "user", "content": current_turn}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content="### Final Analysis and Action Plan\n\nThe file should be removed in a later implementation step.",
        tool_calls=None,
        current_tool_definitions=[{"name": "apply_patch_workspace"}, {"name": "read_workspace_file"}],
        current_step=None,
        current_step_index=0,
        current_step_iterations=0,
        current_step_max_iterations=2,
        current_step_tool_activity=False,
        current_step_wrapup_forced=False,
        active_steps=[],
        current_turn_content=current_turn,
        capability_type="coding",
        tool_context=type("ToolContext", (), {"workspace_root": "/tmp/repo"})(),
        request_analysis={"required_domains": ["implementation"], "user_request": current_turn},
        context_plan=None,
        turn_tool_history=turn_tool_history,
        step_tool_history=[],
        executed_tool_names={"prepare_bitbucket_repository", "read_workspace_file"},
        covered_evidence_axes=set(),
        workflow_contract={"workflow_id": "coding_change_tdd", "verification_contract": {"commands": ["pytest"]}},
        tdd_cycle_state=None,
        total_tokens_in=0,
        total_tokens_out=0,
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        consecutive_coding_no_execution_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_transitional_tool_call_preamble=is_transitional_tool_call_preamble,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        allows_noop_step_completion=lambda step, content: False,
        build_required_tool_reminder=lambda step: "Use the required tool.",
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        build_tdd_cycle_incomplete_reminder=lambda step, state: "tdd incomplete",
        build_initial_tdd_cycle_state=lambda: {},
        is_tdd_cycle_complete=lambda state: True,
        is_tdd_cycle_step=lambda step: False,
        _has_meaningful_coding_execution=lambda history: True,
        _is_probable_coding_change_request=lambda **kwargs: True,
        _looks_like_coding_intent_only_response=lambda content: False,
        _is_self_review_step=lambda step: False,
        _is_self_review_step_complete=lambda step, history: True,
        _build_incomplete_self_review_reminder=lambda step: "self review incomplete",
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: False,
    ))

    assert outcome["action"] == "continue"
    assert any(
        message["role"] == "system" and "still in analysis-only mode" in message["content"]
        for message in messages
    )
    assert not any(
        message["role"] == "system" and "summary" in message["content"].lower()
        for message in messages
    )
