"""Person identity follow-up guards and the Jira and source family evidence they accept."""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_response_followup import handle_followup_response_guards
from app.agent.loops.response._loop_response_followup_inputs import FollowupGuardInputs
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist


@pytest.mark.asyncio
async def test_person_identity_followup_guard_does_not_force_jira_specific_tool() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-person",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Alice Example is a Jira user.",
        tool_calls=None,
        current_step=None,
        current_turn_content="Who is Alice Example?",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[
            {
                "tool_name": "search_jira_users",
                "result": {"users": [{"display_name": "Alice Example", "name": "alice"}], "total": 1},
            }
        ],
        step_tool_history=[],
        executed_tool_names={"search_jira_users"},
        covered_evidence_axes=set(),
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "source_strategy": "person_identity",
            "allowed_tools": ["search_jira_tickets", "search_confluence", "knowledge_search"],
        },
        workflow_id="source_evidence_lookup",
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
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: True,
    ))

    assert outcome["action"] == "none"
    assert outcome["consecutive_non_progress_response_count"] == 0
    assert "forced_tool_calls" not in outcome
    assert messages == []


@pytest.mark.asyncio
async def test_person_identity_followup_guard_does_not_require_specific_jira_ticket_search() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-person",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Alice Example is a Jira user with no Confluence matches.",
        tool_calls=None,
        current_step=None,
        current_turn_content="Who is Alice Example?",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[
            {"tool_name": "search_jira_users", "result": {"users": [{"display_name": "Alice Example"}], "total": 1}},
            {
                "tool_name": "knowledge_search",
                "result": {"state": "ok", "result_count": 1, "evidence": [{"text": "Alice Example, engineer."}]},
            },
            {"tool_name": "search_confluence", "result": {"total": 0, "results": []}},
        ],
        step_tool_history=[],
        executed_tool_names={"search_jira_users", "knowledge_search", "search_confluence"},
        covered_evidence_axes=set(),
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "source_strategy": "person_identity",
            "allowed_tools": ["search_jira_tickets", "search_confluence", "knowledge_search"],
        },
        workflow_id="source_evidence_lookup",
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
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: True,
    ))

    assert outcome["action"] == "none"
    assert "forced_tool_calls" not in outcome
    assert messages == []


@pytest.mark.asyncio
async def test_person_identity_followup_guard_accepts_jira_work_and_additional_source_families() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-person",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content=(
            "Alice Example is a Jira user. Evidence checked: Jira user lookup, Jira work items, "
            "Knowledge, and Confluence. Jira tickets returned 4 matches; Confluence returned 0 matches, "
            "so Confluence coverage is a missing-evidence gap."
        ),
        tool_calls=None,
        current_step=None,
        current_turn_content="Who is Alice Example?",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[
            {"tool_name": "search_jira_users", "result": {"users": [{"display_name": "Alice Example"}], "total": 1}},
            {"tool_name": "search_jira_tickets", "result": {"total": 4, "results": [{"key": "RIVER-1"}]}},
            {
                "tool_name": "knowledge_search",
                "result": {"state": "ok", "result_count": 1, "evidence": [{"text": "Alice Example, engineer."}]},
            },
            {"tool_name": "search_confluence", "result": {"total": 0, "results": []}},
        ],
        step_tool_history=[],
        executed_tool_names={"search_jira_users", "search_jira_tickets", "knowledge_search", "search_confluence"},
        covered_evidence_axes=set(),
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "source_strategy": "person_identity",
            "allowed_tools": ["search_jira_tickets", "search_confluence", "knowledge_search"],
        },
        workflow_id="source_evidence_lookup",
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
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: True,
    ))

    assert outcome["action"] == "none"
    assert messages == []
