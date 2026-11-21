"""Transition guards: repeated placeholders, prompt-word counts, empty governed searches, step summaries and step limits."""

from __future__ import annotations

import pytest

from app.agent.core.guards.response_guards import (
    build_stalled_step_message,
    is_non_substantive_assistant_response,
    is_transitional_assistant_response,
    looks_like_step_completion_summary,
)
from app.agent.loops.response._loop_response_transition_inputs import TransitionGuardInputs
from app.agent.loops.response._loop_response_transitions import handle_transition_response_guards
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist, _noop_trace


@pytest.mark.asyncio
async def test_transition_guard_stops_repeated_textual_tool_request_placeholders() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-knowledge",
        runtime={"provider_name": "bedrock"},
        response={"usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        request_messages=[{"role": "user", "content": "what can you tell me about Report Builder?"}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Tool request knowledge_read: {'key': 'Report Builder'}",
        tool_calls=None,
        current_tool_definitions=[],
        current_step=None,
        has_followup_steps=False,
        turn_tool_history=[
            {
                "tool_name": "knowledge_search",
                "result": {
                    "state": "ok",
                    "result_count": 2,
                    "evidence": [
                        {
                            "source_title": "Report Builder Startup",
                            "text": "Startup documentation covers init behavior and runtime prerequisites.",
                            "cite_as": "[Report Builder Startup](https://docs.example.local/report-builder-startup)",
                        },
                        {
                            "source_title": "Report Builder Maintenance",
                            "text": "Maintenance notes explain release operations and export checks.",
                            "cite_as": (
                                "[Report Builder Maintenance]"
                                "(https://docs.example.local/report-builder-maintenance)"
                            ),
                        },
                    ],
                },
            },
        ],
        consecutive_non_progress_response_count=1,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        workflow_id="knowledge_request",
    ))

    assert outcome["action"] == "return"
    assert outcome["consecutive_non_progress_response_count"] == 2
    assert "I found 2 matching Knowledge entries" in outcome["yield_content"]
    assert "Startup documentation covers init behavior" in outcome["yield_content"]
    assert "Maintenance notes explain release operations" in outcome["yield_content"]
    assert "Sources:" in outcome["yield_content"]
    assert "https://docs.example.local/report-builder-startup" in outcome["yield_content"]


@pytest.mark.asyncio
async def test_transition_guard_never_salvages_a_count_keyed_on_prompt_words() -> None:
    # The security-group count salvage keyed on "security group" in the prompt is deleted; a
    # stalled AWS lookup ends with the generic stalled message, whatever the user asked.
    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-aws",
        runtime={"provider_name": "bedrock"},
        response={"usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        request_messages=[{"role": "user", "content": "How many securitygroup do we have?"}],
        messages=[],
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Tool request list_aws_ec2_security_groups: {'region': 'eu-central-1'}",
        tool_calls=None,
        current_tool_definitions=[],
        current_step=None,
        has_followup_steps=False,
        turn_tool_history=[
            {
                "tool_name": "aws_topology_snapshot",
                "result": {
                    "account_id": "123456789012",
                    "region": "eu-central-1",
                    "diagram_brief": {
                        "selected_nodes": [
                            {"type": "security_group", "label": "sg-a"},
                            {"type": "security_group", "label": "sg-b"},
                            {"type": "vpc", "label": "vpc-a"},
                        ]
                    },
                },
            }
        ],
        consecutive_non_progress_response_count=1,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        workflow_id="aws_infrastructure_lookup",
    ))

    assert outcome["action"] == "return"
    assert "security groups" not in outcome["yield_content"]
    assert outcome["yield_content"].startswith("Agent stopped because")


@pytest.mark.asyncio
async def test_transition_guard_answers_nothing_documented_after_an_empty_governed_search() -> None:
    messages: list[dict[str, str]] = []

    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-knowledge",
        runtime={"provider_name": "bedrock"},
        response={"usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        request_messages=[{"role": "user", "content": "what can you tell me about Report Builder?"}],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="amazon.nova-2-lite-v1:0",
        content="Tool request instruction_get: {'domain': 'knowledge'}",
        tool_calls=None,
        current_tool_definitions=[],
        current_step=None,
        has_followup_steps=False,
        turn_tool_history=[
            {
                "tool_name": "knowledge_search",
                "result": {"state": "ok", "result_count": 0, "evidence": []},
            }
        ],
        consecutive_non_progress_response_count=1,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        workflow_id="knowledge_request",
    ))

    assert outcome["action"] == "return"
    assert "found nothing documented" in outcome["yield_content"]


@pytest.mark.asyncio
async def test_transition_guard_allows_step_completion_summary_when_followup_step_exists() -> None:
    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=None,
        session_id="session-1",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=[],
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 2},
        usage_model="claude-haiku-4.5",
        content="## Step 2/3: Write Research Plan JSON\n\nI'll now design and write the plan file.",
        tool_calls=None,
        current_tool_definitions=[{"name": "write_workspace_file"}],
        current_step={"name": "Gather Sources"},
        has_followup_steps=True,
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=build_stalled_step_message,
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        workflow_id="research_document",
    ))

    assert outcome["action"] == "none"
    assert outcome["consecutive_transitional_response_count"] == 0


@pytest.mark.asyncio
async def test_transition_guard_respects_step_specific_transitional_limit() -> None:
    outcome = await handle_transition_response_guards(TransitionGuardInputs(
        db=_DummyDB(),
        session_id="session-2",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=[],
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 3},
        usage_model="claude-haiku-4.5",
        content="I'll now do a more specific search for the delegated task.",
        tool_calls=None,
        current_tool_definitions=[{"name": "web_search"}],
        current_step={
            "name": "Execute Delegated Sub-task",
            "stepConfig": {"max_transitional_responses": 1},
        },
        has_followup_steps=False,
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        is_transitional_assistant_response=is_transitional_assistant_response,
        is_non_substantive_assistant_response=is_non_substantive_assistant_response,
        looks_like_step_completion_summary=looks_like_step_completion_summary,
        build_stalled_step_message=build_stalled_step_message,
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        workflow_id="research_document",
    ))

    assert outcome["action"] == "return"
    assert outcome["consecutive_transitional_response_count"] == 1
