"""Follow-up guards for operations contracts, declared missing actions and AWS gateway evidence."""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_response_followup import handle_followup_response_guards
from app.agent.loops.response._loop_response_followup_inputs import FollowupGuardInputs
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist


@pytest.mark.asyncio
async def test_followup_guard_does_not_force_operations_without_contract() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-ops",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="claude-haiku-4.5",
        content="I will first check rollout status and report back.",
        tool_calls=None,
        current_step=None,
        current_turn_content="Deploy the current release candidate and verify the rollout status.",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[],
        step_tool_history=[],
        executed_tool_names=set(),
        covered_evidence_axes=set(),
        workflow_contract=None,
        workflow_id="",
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
async def test_evidence_completion_guard_requires_declared_missing_action() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-release",
        runtime={"provider_name": "bedrock"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="amazon.nova-2-lite-v1:0",
        content="The next release is shop_2.4.10. Would you like me to retrieve the Jira issues?",
        tool_calls=None,
        current_step=None,
        current_turn_content="What is the next release and what changes are in this release?",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[
            {
                "tool_name": "list_jira_versions",
                "result": {
                    "versions": [
                        {
                            "name": "shop_2.4.10",
                            "released": False,
                            "archived": False,
                            "release_date": "2026-06-23",
                        }
                    ]
                },
            }
        ],
        step_tool_history=[],
        executed_tool_names={"list_jira_versions"},
        covered_evidence_axes=set(),
        workflow_contract={
            "workflow_id": "source_evidence_lookup",
            "workflow_class": "source_evidence_lookup",
            "source_strategy": "release_status",
            "release_focus": "next",
            "source_steps": [
                {"tool": "list_jira_versions", "args": {}},
                {"tool": "search_jira_tickets", "args": {"jql": "fixVersion = {release_name}"}},
            ],
            "allowed_tools": ["list_jira_versions", "search_jira_tickets"],
            "evidence_completion": {
                "required_actions": [
                    {
                        "tool": "search_jira_tickets",
                        "evidence_label": "linked change evidence",
                        "after_successful_tools": ["list_jira_versions"],
                        "when_user_message_contains_any": ["changes"],
                        "guidance": "Use prior version evidence to choose arguments.",
                    }
                ]
            },
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
        workflow_artifact_contract_satisfied=lambda contract, turn_tool_history=None: False,
    ))

    assert outcome["action"] == "continue"
    assert any(
        message["role"] == "system"
        and "workflow/tool evidence contract is not complete" in message["content"]
        and "`search_jira_tickets`" in message["content"]
        for message in messages
    )


@pytest.mark.asyncio
async def test_operations_followup_guard_accepts_aws_gateway_evidence() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_followup_response_guards(FollowupGuardInputs(
        db=_DummyDB(),
        session_id="session-ops",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="claude-haiku-4.5",
        content='{"account":"123456789012"}',
        tool_calls=None,
        current_step=None,
        current_turn_content="Use AWS STS to verify the runtime identity.",
        request_analysis={},
        context_plan=None,
        turn_tool_history=[],
        step_tool_history=[],
        executed_tool_names={"aws_read_operation"},
        covered_evidence_axes=set(),
        workflow_contract=None,
        workflow_id="",
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
