"""Follow-up guards for loaded knowledge details and workflow artifacts after repeated no-tool responses."""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_response_followup import handle_followup_response_guards
from app.agent.loops.response._loop_response_followup_inputs import FollowupGuardInputs
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist


@pytest.mark.asyncio
async def test_knowledge_followup_guard_accepts_loaded_detail_evidence() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-knowledge",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Report Builder is a reporting utility backed by the loaded evidence.",
        tool_calls=None,
        current_step=None,
        current_turn_content="what can you tell me about Report Builder?",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[
            {
                "tool_name": "knowledge_read",
                "params": {"content_level": "full", "key": "report-builder-guide"},
                "result": {
                    "title": "Report Builder guide",
                    "content": "Report Builder builds weekly order reports from the shop's exports.",
                },
            }
        ],
        step_tool_history=[],
        executed_tool_names={"knowledge_read"},
        covered_evidence_axes=set(),
        workflow_contract={"workflow_id": "knowledge_request"},
        workflow_id="knowledge_request",
        tdd_cycle_state=None,
        consecutive_non_progress_response_count=0,
        consecutive_coding_no_execution_count=0,
        consecutive_transitional_response_count=0,
        persist_suppressed_runtime_response=_noop_persist,
        persist_traced_assistant_message=_noop_message,
        build_stalled_step_message=lambda step: "stalled",
        build_tdd_cycle_incomplete_reminder=lambda step, state: "tdd incomplete",
        build_initial_tdd_cycle_state=lambda: {},
        is_tdd_cycle_complete=lambda state: True,
        is_tdd_cycle_step=lambda step: False,
        _is_self_review_step=lambda step: False,
        _is_self_review_step_complete=lambda step, history: True,
        _build_incomplete_self_review_reminder=lambda step: "self review incomplete",
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: False,
    ))

    assert outcome["action"] == "none"
    assert messages == []


@pytest.mark.asyncio
async def test_workflow_artifact_followup_guard_returns_neutral_message_after_repeated_no_tool_responses() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-doc",
        runtime={"provider_name": "copilot"},
        response={"usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        request_messages=[{"role": "user", "content": "Create a cited Word report."}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="claude-haiku-4.5",
        content="I found the sources and will now build the report.",
        tool_calls=None,
        current_step={"name": "Gather Delegated Evidence"},
        current_turn_content="Create a cited Word report.",
        request_analysis={"enforce_evidence_coverage": False},
        context_plan=None,
        turn_tool_history=[],
        step_tool_history=[],
        executed_tool_names=set(),
        covered_evidence_axes=set(),
        workflow_contract={"workflow_id": "research_document", "artifact_path": "/tmp/report.docx"},
        workflow_id="research_document",
        tdd_cycle_state=None,
        consecutive_non_progress_response_count=1,
        consecutive_coding_no_execution_count=0,
        consecutive_transitional_response_count=0,
        persist_suppressed_runtime_response=_noop_persist,
        persist_traced_assistant_message=_noop_message,
        build_stalled_step_message=lambda step: "stalled on missing tool use",
        build_tdd_cycle_incomplete_reminder=lambda step, state: "tdd incomplete",
        build_initial_tdd_cycle_state=lambda: {},
        is_tdd_cycle_complete=lambda state: True,
        is_tdd_cycle_step=lambda step: False,
        _is_self_review_step=lambda step: False,
        _is_self_review_step_complete=lambda step, history: True,
        _build_incomplete_self_review_reminder=lambda step: "self review incomplete",
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: False,
    ))

    assert outcome["action"] == "return"
    assert outcome["yield_content"] == "stalled on missing tool use"
    assert outcome["consecutive_non_progress_response_count"] == 2
    assert any(message["role"] == "system" and "workflow contract still requires a finished artifact" in message["content"] for message in messages)


@pytest.mark.asyncio
async def test_workflow_followup_guard_returns_substantive_model_draft_after_repeated_no_tool_responses() -> None:
    messages: list[dict[str, str]] = []
    model_draft = (
        "## Evidence summary\n\n"
        "The collected Knowledge evidence shows that Report Builder is a Python utility that builds weekly order "
        "reports from the shop's exports. It reads the export files, groups the orders by week and region, and "
        "writes one summary report per week with totals and open returns. The deployment evidence also shows "
        "that it runs once a week on a schedule, with its settings supplied through a configuration file and "
        "the finished reports stored next to the exports."
    )

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-knowledge",
        runtime={"provider_name": "bedrock"},
        response={"usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        request_messages=[{"role": "user", "content": "Explain Report Builder."}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="amazon.nova-2-lite-v1:0",
        content=model_draft,
        tool_calls=None,
        current_step=None,
        current_turn_content="Explain Report Builder.",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[],
        step_tool_history=[],
        executed_tool_names=set(),
        covered_evidence_axes=set(),
        workflow_contract={"workflow_id": "knowledge_request"},
        workflow_id="knowledge_request",
        tdd_cycle_state=None,
        consecutive_non_progress_response_count=1,
        consecutive_coding_no_execution_count=0,
        consecutive_transitional_response_count=0,
        persist_suppressed_runtime_response=_noop_persist,
        persist_traced_assistant_message=_noop_message,
        build_stalled_step_message=lambda step: "Agent stopped because the final step stalled.",
        build_tdd_cycle_incomplete_reminder=lambda step, state: "tdd incomplete",
        build_initial_tdd_cycle_state=lambda: {},
        is_tdd_cycle_complete=lambda state: True,
        is_tdd_cycle_step=lambda step: False,
        _is_self_review_step=lambda step: False,
        _is_self_review_step_complete=lambda step, history: True,
        _build_incomplete_self_review_reminder=lambda step: "self review incomplete",
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: False,
    ))

    assert outcome["action"] == "return"
    assert outcome["yield_content"] == model_draft
    assert "Agent stopped because" not in outcome["yield_content"]
