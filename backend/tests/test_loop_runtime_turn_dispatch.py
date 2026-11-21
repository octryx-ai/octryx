"""execute_runtime_turn salvages a completed document, passes the retry policy to the fallback and runs the trace-only planner first."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.core.runtime.turn_execution_binding import bind_turn_execution_snapshot, clear_turn_execution_snapshot
from app.agent.loops.runtime._loop_runtime_turn import execute_runtime_turn
from app.agent.loops.runtime._loop_runtime_turn_inputs import RuntimeTurnInputs
from tests.loop_runtime_turn_support import build_runtime_turn_kwargs


@pytest.mark.asyncio
async def test_execute_runtime_turn_returns_success_when_runtime_error_is_salvaged_after_document_completion():
    captured: dict[str, Any] = {}

    class _RuntimeError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("All configured runtime targets failed: empty assistant output without tool calls")
            self.runtime_attempts = [
                {
                    "provider": "copilot",
                    "model": "claude-sonnet-4.5",
                    "target_id": "doc",
                    "status": "error",
                    "error_class": "empty_response",
                }
            ]

    async def _dispatch_loop_runtime_response(**kwargs):
        raise _RuntimeError()

    async def _persist_traced_assistant_message(**kwargs):
        captured.update(kwargs)
        return None

    async def _build_runtime_error_salvage_message(**kwargs):
        return "The requested office artifact was created successfully.\n\nFile: `ticketing_research_document.docx`."

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["persist_traced_assistant_message"] = _persist_traced_assistant_message
    kwargs["_build_runtime_error_salvage_message"] = _build_runtime_error_salvage_message
    kwargs["request_analysis"] = {
        "workflow_contract": {
            "workflow_id": "research_document",
            "artifact_type": "document",
            "topic": "ticketing API integration",
            "artifact_path": "ticketing_research_document.docx",
            "document_plan_path": "ticketing_research_document_plan.json",
        }
    }
    kwargs["turn_tool_history"] = [
        {
            "tool_name": "write_workspace_file",
            "parameters": {"path": "ticketing_research_document_plan.json"},
            "result": {"path": "ticketing_research_document_plan.json"},
        },
        {
            "tool_name": "ingest_document_source",
            "parameters": {"url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/"},
            "result": {
                "source": {
                    "url": "https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/",
                    "title": "Jira Cloud REST API",
                }
            },
        },
        {
            "tool_name": "build_word_template_script",
            "parameters": {"file_path": "ticketing_research_document.docx"},
            "result": {
                "relative_path": "ticketing_research_document.docx",
                "file_path": "/tmp/ticketing_research_document.docx",
                "validation": {"valid": True},
            },
        },
        {
            "tool_name": "get_office_document_info",
            "parameters": {"file_path": "ticketing_research_document.docx"},
            "result": {"relative_path": "ticketing_research_document.docx", "paragraph_count": 12},
        },
    ]
    kwargs["workflow_contract_from_request_analysis"] = lambda analysis: analysis.get("workflow_contract")

    # Salvage runs only for a bound turn: its admission instant bounds what it may read.
    bind_turn_execution_snapshot(kwargs["session_id"], {})
    try:
        result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))
    finally:
        clear_turn_execution_snapshot(kwargs["session_id"])

    assert result["action"] == "return"
    assert "ticketing_research_document.docx" in result["event"]["content"]
    assert captured["content"] == result["event"]["content"]


@pytest.mark.asyncio
async def test_execute_runtime_turn_passes_runtime_retry_policy_to_fallback():
    captured: dict[str, Any] = {}

    async def _dispatch_loop_runtime_response(**kwargs):
        await kwargs["chat_with_runtime_fallback"](
            runtimes=[],
            messages=[],
            tools=None,
            max_tokens=128,
            reasoning_effort=None,
            request_timeout_seconds=7,
        )
        return (
            {
                "content": "ok",
                "tool_calls": [],
                "model": "fallback-model",
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            },
            {"provider_name": "openrouter", "model": "fallback-model", "target_id": "fallback"},
            [],
            None,
        )

    async def _chat_with_runtime_fallback(**kwargs):
        captured.update(kwargs)
        return {"content": "ok", "tool_calls": [], "usage": {}, "model": "fallback-model"}, {}, []

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["chat_with_runtime_fallback"] = _chat_with_runtime_fallback
    kwargs["runtime_settings"] = {
        "runtime_unreachable_retry_max_retries": 5,
        "runtime_unreachable_retry_pause_seconds": 9,
    }

    result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))

    assert result["action"] == "ok"
    assert captured["retry_policy"] == {
        "max_retries": 5,
        "pause_seconds": 9,
        "fallback_mode": "all_runtimes",
        # The chain has no governed setting and no gateway target, so the
        # historical default applies and says so.
        "fallback_mode_source": "default",
    }


@pytest.mark.asyncio
async def test_execute_runtime_turn_invokes_trace_only_planner_before_main_dispatch():
    captured: dict[str, Any] = {"calls": []}

    async def _dispatch_loop_runtime_response(**kwargs):
        captured["main_context_snapshot"] = kwargs["request_messages"]
        return (
            {
                "content": "ok",
                "tool_calls": [],
                "model": "fallback-model",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
            {"provider_name": "openrouter", "model": "fallback-model", "target_id": "fallback"},
            [],
            None,
        )

    async def _chat_with_runtime_fallback(**kwargs):
        captured["calls"].append(kwargs)
        return (
            {
                "content": (
                    '{"version":1,"mode":"trace_only","intent_class":"unknown","confidence":0.2,'
                    '"selected_tools":[],"stop_criteria":["direct_answer"],"max_tool_calls":0,'
                    '"requires_clarification":true}'
                ),
                "tool_calls": [],
                "usage": {"prompt_tokens": 2, "completion_tokens": 2},
                "model": "planner-model",
            },
            {"provider_name": "openrouter", "model": "planner-model"},
            [{"status": "success"}],
        )

    async def _record_usage_event(**kwargs):
        captured.setdefault("usage_events", []).append(kwargs)

    async def _persist_runtime_assistant_response(**kwargs):
        captured["context_snapshot"] = kwargs["context_snapshot"]
        return {"id": "assistant"}, {"id": "trace"}

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["chat_with_runtime_fallback"] = _chat_with_runtime_fallback
    kwargs["record_usage_event"] = _record_usage_event
    kwargs["persist_runtime_assistant_response"] = _persist_runtime_assistant_response
    kwargs["runtime_settings"] = {"llm_tool_planner_trace_call_enabled": True}
    kwargs["context_snapshot"] = {
        "session_tool_catalog": {"entries": [], "tool_count": 0},
        "llm_tool_plan_prompt_packet": {"version": 1, "allowed_tool_catalog": []},
    }

    result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))

    assert result["action"] == "ok"
    assert len(captured["calls"]) == 1
    assert captured["calls"][0]["tools"] is None
    assert captured["context_snapshot"]["llm_tool_plan_model_response"]["call_status"] == "completed"
    assert any(event["phase"] == "planner_call" for event in captured["context_snapshot"]["decision_timeline"])
    assert captured["usage_events"][0]["usage"]["planner_call"] is True
