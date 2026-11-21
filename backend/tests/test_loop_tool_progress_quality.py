"""Progress quality guards block unsupported claims, and tool activity stall detection stops idle loops."""

from app.agent.loops.control._loop_progress_quality import (
    detect_tool_activity_stall,
    detect_unsupported_no_tool_progress_claim,
)
from app.agent.loops.response._loop_no_tool import handle_no_tool_response
from app.agent.loops.response._loop_no_tool_inputs import NoToolResponseInputs


def test_progress_quality_blocks_unsupported_implementation_claim():
    event = detect_unsupported_no_tool_progress_claim(
        is_governed=True,
        assistant_content="I updated the Terraform files and removed the obsolete block.",
        history=[],
    )

    assert event is not None
    assert event["claim"] == "completion"
    assert event["action"] == "require_tool_evidence_or_blocker"
    assert "mutation tool evidence" in event["missing_evidence"]


async def test_no_tool_handler_continues_on_unsupported_implementation_claim():
    captured: dict[str, object] = {}

    class FakeDb:
        async def commit(self) -> None:
            captured["committed"] = True

    class FakeMessage:
        id = "assistant-message-1"

    async def persist_runtime_thread_context(**kwargs):
        captured["thread_context"] = kwargs
        return {"id": "thread-context"}

    async def persist_suppressed_runtime_response(**kwargs):
        captured["suppressed"] = kwargs

    async def persist_traced_assistant_message(**kwargs):
        captured["traced"] = kwargs

    result = await handle_no_tool_response(NoToolResponseInputs(
        db=FakeDb(),
        session_id="session-1",
        request_messages=[],
        context_snapshot={},
        response={"usage": {}},
        runtime_attempts=[],
        runtime={"provider_name": "test"},
        usage_model="model",
        content="I updated the Terraform configuration.",
        assistant_msg=FakeMessage(),
        turn_trace=None,
        current_turn_content="You are Octryx's governed coding agent. Execute this approved Work Plan.",
        request_analysis={
            "workflow_contract": {
                "workflow_id": "coding_change_tdd",
                "verification_contract": {"commands": [{"command": "true", "source": "change_unit"}]},
            }
        },
        turn_tool_history=[],
        required_domains=set(),
        covered_summary_domains=set(),
        covered_evidence_axes=set(),
        current_step=None,
        current_step_index=0,
        active_steps=[],
        current_step_wrapup_forced=False,
        duplicate_no_tool_response_count=0,
        repeated_previous_step_summary_count=0,
        last_no_tool_response_signature=None,
        last_no_tool_response_content="",
        last_no_tool_response_step_index=None,
        existing_thread_context=None,
        assistant_no_tool_response_signature=lambda _content: "implementation-claim",
        assistant_no_tool_response_similarity=lambda _previous, _current: 0.0,
        looks_like_step_completion_summary=lambda _content: False,
        detect_no_tool_stuck_loop=lambda **_kwargs: None,
        plan_loop_recovery=lambda **_kwargs: {},
        persist_suppressed_runtime_response=persist_suppressed_runtime_response,
        persist_runtime_thread_context=persist_runtime_thread_context,
        persist_traced_assistant_message=persist_traced_assistant_message,
        runtime_settings={},
        total_tokens_in=0,
        total_tokens_out=0,
        history_count=0,
        summarize_threshold=100,
    ))

    assert result["action"] == "continue"
    assert result["progress_quality_event"]["claim"] == "completion"
    assert "mutation tool evidence" in result["followup_system_message"]
    assert captured["committed"] is True
    raw_output = captured["thread_context"]["raw_output"]
    assert raw_output["progress_quality_event"]["kind"] == "unsupported_no_tool_progress_claim"


def test_progress_quality_blocks_unsupported_validation_claim():
    event = detect_unsupported_no_tool_progress_claim(
        is_governed=True,
        assistant_content="The change is validated and tests passed.",
        history=[{"tool_name": "edit_workspace_file", "result": {"status": "edited"}}],
    )

    assert event is not None
    assert event["claim"] == "completion"
    assert "validation tool evidence" in event["missing_evidence"]


def test_progress_quality_does_not_treat_missing_tool_as_successful_validation():
    event = detect_unsupported_no_tool_progress_claim(
        is_governed=True,
        assistant_content="Validation passed and the change is ready.",
        history=[
            {"tool_name": "edit_workspace_file", "result": {"status": "edited"}},
            {
                "tool_name": "run_cli_command",
                "result": {
                    "command": "terraform validate",
                    "exit_code": 127,
                    "validation_outcome": {"status": "missing_tool", "blocker": "validation_tool_missing"},
                },
            },
        ],
    )

    assert event is not None
    assert event["claim"] == "completion"
    assert "validation tool evidence" in event["missing_evidence"]


def test_progress_quality_blocks_completion_without_delivery_evidence():
    event = detect_unsupported_no_tool_progress_claim(
        is_governed=True,
        assistant_content="Done and ready for review.",
        history=[
            {"tool_name": "edit_workspace_file", "result": {"status": "edited"}},
            {
                "tool_name": "run_cli_command",
                "parameters": {"command": "git diff --check"},
                "result": {"exit_code": 0},
            },
        ],
    )

    assert event is not None
    assert event["claim"] == "completion"
    assert "commit/PR delivery evidence" in event["missing_evidence"]


def test_progress_quality_allows_completion_with_state_evidence():
    event = detect_unsupported_no_tool_progress_claim(
        is_governed=True,
        assistant_content="Done and ready for review.",
        history=[
            {"tool_name": "edit_workspace_file", "result": {"status": "edited"}},
            {
                "tool_name": "run_cli_command",
                "parameters": {"command": "git diff --check"},
                "result": {"exit_code": 0},
            },
            {"tool_name": "create_bitbucket_pull_request", "result": {"status": "created"}},
        ],
    )

    assert event is None


def test_tool_activity_stall_detects_evidence_without_productive_action():
    event = detect_tool_activity_stall(
        history=[
            {"tool_name": "read_workspace_file", "result": {"path": "a.tf"}},
            {"tool_name": "grep_workspace", "result": {"matches": []}},
        ],
        activity_tool_names={"read_workspace_file", "grep_workspace"},
        productive_tool_names={"edit_workspace_file"},
        limit=2,
    )

    assert event is not None
    assert event["kind"] == "tool_activity_stall"
    assert event["action"] == "force_next_productive_action"
    assert event["tool_counts"] == {"read_workspace_file": 1, "grep_workspace": 1}


def test_tool_activity_stall_stops_after_hard_limit():
    event = detect_tool_activity_stall(
        history=[
            {"tool_name": "read_workspace_file", "result": {"path": "a.tf"}},
            {"tool_name": "read_workspace_file", "result": {"path": "b.tf"}},
            {"tool_name": "read_workspace_file", "result": {"path": "c.tf"}},
        ],
        activity_tool_names={"read_workspace_file"},
        productive_tool_names={"edit_workspace_file"},
        limit=2,
        hard_limit=3,
    )

    assert event is not None
    assert event["hard_stop"] is True
    assert event["action"] == "stop_with_blocker"
