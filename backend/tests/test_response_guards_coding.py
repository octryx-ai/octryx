"""Required tool guards after a ready workflow artifact and coding guards for clarifications and no-tool responses."""

from __future__ import annotations

import pytest

from app.agent.loops.response._loop_coding_guard_nudges import CodingGuardInputs
from app.agent.loops.response._loop_response_coding import handle_coding_response_guards
from tests.response_guards_support import _DummyDB, _noop_message, _noop_persist, _noop_trace


@pytest.mark.asyncio
async def test_required_tool_guard_skips_after_workflow_artifact_ready() -> None:
    messages: list[dict[str, str]] = []
    outcome = await handle_coding_response_guards(CodingGuardInputs(
        db=_DummyDB(),
        session_id="session-3",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="claude-haiku-4.5",
        content="## Ready\n\nThe presentation is built and validated at `/tmp/create_presentation.pptx`.",
        tool_calls=None,
        current_step={"name": "Finalize Presentation", "allowedTools": ["get_office_document_info"]},
        current_step_index=2,
        current_step_iterations=0,
        current_step_max_iterations=2,
        current_step_tool_activity=False,
        active_steps=[
            {"name": "Plan"},
            {"name": "Build"},
            {"name": "Finalize Presentation", "allowedTools": ["get_office_document_info"]},
        ],
        workflow_artifact_ready_for_final_response=True,
        current_turn_content="Create a presentation from the provided material.",
        capability_type="documentation",
        tool_context=type("ToolContext", (), {"workspace_root": "/tmp"})(),
        turn_tool_history=[
            {"tool_name": "build_presentation_script", "result": {"relative_path": "create_presentation.pptx"}},
            {"tool_name": "validate_office_document", "result": {"valid": True}},
            {"tool_name": "get_office_document_info", "result": {"slide_count": 5}},
        ],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        consecutive_coding_no_execution_count=0,
        allows_noop_step_completion=lambda step, content: False,
        build_required_tool_reminder=lambda step: "Use the required tool.",
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        _has_meaningful_coding_execution=lambda history: False,
        _is_probable_coding_change_request=lambda **kwargs: False,
        _looks_like_coding_intent_only_response=lambda content: False,
    ))

    assert outcome["action"] == "none"
    assert messages == []


@pytest.mark.asyncio
async def test_coding_guard_allows_focused_clarification_for_private_dependency_blockers() -> None:
    messages: list[dict[str, str]] = []
    content = """
I checked the repository and the Maven files. Before I make risky changes, I have focused
clarification questions, because the migration touches private artifacts:

1. Please confirm the branch name `codex/java25-springboot403-acme-orders`?
2. Which version of the private parent POM `com.example.corp-301-5.maven.pom:corp-parent`
   supports Java 25 and Spring Boot 4.0.3?
3. Which versions of the private `com.example.pps.sb:sb-auto-*` dependencies are approved for
   Spring Boot 4?
4. Should I only plan the migration until approval, or already change compatible files?
"""

    outcome = await handle_coding_response_guards(CodingGuardInputs(
        db=_DummyDB(),
        session_id="session-clarify",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={},
        usage_model="gpt-5.3-codex",
        content=content,
        tool_calls=None,
        current_step=None,
        current_step_index=0,
        current_step_iterations=0,
        current_step_max_iterations=2,
        current_step_tool_activity=False,
        active_steps=[],
        workflow_artifact_ready_for_final_response=False,
        current_turn_content=(
            "Migrate acme-orders-access-proxy from Java 21 and Spring Boot 3.4 to Java 25 and "
            "Spring Boot 4.0.3. Use a dedicated branch."
        ),
        capability_type="change",
        tool_context=type(
            "ToolContext",
            (),
            {"workspace_root": "/Users/dev/Documents/OCX/AI/externalrepos/acme-orders-access-proxy"},
        )(),
        turn_tool_history=[
            {"tool_name": "analyze_workspace_repository", "result": {"status": "ok"}},
            {"tool_name": "read_workspace_file", "result": {"path": "pom.xml"}},
        ],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        consecutive_coding_no_execution_count=0,
        allows_noop_step_completion=lambda step, content: False,
        build_required_tool_reminder=lambda step: "Use the required tool.",
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        _has_meaningful_coding_execution=lambda history: False,
        _is_probable_coding_change_request=lambda **kwargs: True,
        _looks_like_coding_intent_only_response=lambda content: False,
    ))

    assert outcome["action"] == "none"
    assert outcome["consecutive_coding_no_execution_count"] == 0
    assert messages == []


@pytest.mark.asyncio
async def test_coding_guard_still_suppresses_generic_no_tool_coding_response() -> None:
    messages: list[dict[str, str]] = []
    outcome = await handle_coding_response_guards(CodingGuardInputs(
        db=_DummyDB(),
        session_id="session-generic",
        runtime={"provider_name": "copilot"},
        response={"usage": {}},
        request_messages=[],
        messages=messages,
        context_snapshot={},
        runtime_attempts=[],
        runtime_settings={"stuck_loop_no_tool_duplicate_threshold": 3},
        usage_model="gpt-5.3-codex",
        content="I inspected the request and will now update the project files and tests.",
        tool_calls=None,
        current_step=None,
        current_step_index=0,
        current_step_iterations=0,
        current_step_max_iterations=2,
        current_step_tool_activity=False,
        active_steps=[],
        workflow_artifact_ready_for_final_response=False,
        current_turn_content="Implement the requested Java migration.",
        capability_type="change",
        tool_context=type("ToolContext", (), {"workspace_root": "/tmp/repo"})(),
        turn_tool_history=[],
        consecutive_non_progress_response_count=0,
        consecutive_transitional_response_count=0,
        consecutive_coding_no_execution_count=0,
        allows_noop_step_completion=lambda step, content: False,
        build_required_tool_reminder=lambda step: "Use the required tool.",
        build_stalled_step_message=lambda step: "stalled",
        persist_suppressed_runtime_response=_noop_persist,
        persist_turn_trace=_noop_trace,
        persist_traced_assistant_message=_noop_message,
        _has_meaningful_coding_execution=lambda history: False,
        _is_probable_coding_change_request=lambda **kwargs: True,
        _looks_like_coding_intent_only_response=lambda content: True,
    ))

    assert outcome["action"] == "continue"
    assert outcome["consecutive_coding_no_execution_count"] == 1
    assert any(message["role"] == "system" and "coding task" in message["content"] for message in messages)
