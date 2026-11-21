from __future__ import annotations

import json
from typing import Any

import pytest

from app.agent.loops.control._loop_tool_planner import PLANNER_ENABLED_SETTING, maybe_call_trace_only_tool_planner
from app.services.tool_catalog import build_session_tool_catalog
from app.services.tool_planning import build_tool_plan_prompt_packet, build_trace_only_tool_plan_contract
from app.tools.definitions import get_all_definitions


def _definition(name: str) -> dict:
    return get_all_definitions()[name]


def _catalog(*names: str) -> dict:
    return build_session_tool_catalog(
        tool_definitions=[_definition(name) for name in names],
        capability_type="admin",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=None,
    )


def _context_snapshot() -> dict[str, Any]:
    catalog = _catalog("knowledge_search", "knowledge_read")
    draft = build_trace_only_tool_plan_contract(
        current_turn_content="What can you tell me about Report Builder?",
        request_analysis={"requested_domains": ["knowledge"]},
        workflow_contract=None,
        session_tool_catalog=catalog,
    )
    return {
        "session_tool_catalog": catalog,
        "llm_tool_plan_prompt_packet": build_tool_plan_prompt_packet(
            current_turn_content="What can you tell me about Report Builder?",
            request_analysis={"requested_domains": ["knowledge"]},
            workflow_contract=None,
            session_tool_catalog=catalog,
            draft_contract=draft,
        ),
    }


async def _record_usage_event(**kwargs):
    return None


def _normalize(result):
    return result


@pytest.mark.asyncio
async def test_trace_only_tool_planner_does_not_call_runtime_when_disabled():
    async def _chat_with_runtime_fallback(**kwargs):
        raise AssertionError("planner call should be disabled")

    snapshot = _context_snapshot()

    result = await maybe_call_trace_only_tool_planner(
        context_snapshot=snapshot,
        runtime_settings={},
        current_runtimes=[{"provider_name": "test", "model": "model"}],
        provider_reasoning_effort=None,
        request_timeout_seconds=30,
        chat_with_runtime_fallback=_chat_with_runtime_fallback,
        normalize_runtime_chat_result=_normalize,
        record_usage_event=_record_usage_event,
        db=None,
        session_id="session",
        user_id="user",
        request_id="request",
    )

    assert result is None
    assert "llm_tool_plan_model_response" not in snapshot


@pytest.mark.asyncio
async def test_trace_only_tool_planner_records_valid_model_plan_and_usage():
    captured: dict[str, Any] = {}

    async def _chat_with_runtime_fallback(**kwargs):
        captured["chat_kwargs"] = kwargs
        return (
            {
                "content": json.dumps(
                    {
                        "version": 1,
                        "mode": "trace_only",
                        "intent_class": "workflow_process",
                        "confidence": 0.81,
                        "selected_tools": [{"tool": "knowledge_search", "expected_evidence": ["source_evidence"]}],
                        "stop_criteria": ["retrieved_source_evidence"],
                        "max_tool_calls": 2,
                    }
                ),
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
                "model": "planner-model",
            },
            {"provider_name": "test-provider", "model": "planner-model"},
            [{"status": "success"}],
        )

    async def _record_usage(**kwargs):
        captured["usage"] = kwargs

    snapshot = _context_snapshot()

    result = await maybe_call_trace_only_tool_planner(
        context_snapshot=snapshot,
        runtime_settings={PLANNER_ENABLED_SETTING: True},
        current_runtimes=[{"provider_name": "test-provider", "model": "planner-model"}],
        provider_reasoning_effort=None,
        request_timeout_seconds=30,
        chat_with_runtime_fallback=_chat_with_runtime_fallback,
        normalize_runtime_chat_result=_normalize,
        record_usage_event=_record_usage,
        db=None,
        session_id="session",
        user_id="user",
        request_id="request",
    )

    assert captured["chat_kwargs"]["tools"] is None
    assert result["call_status"] == "completed"
    assert result["validation"]["valid"] is True
    assert snapshot["llm_tool_plan_model_response"]["plan"]["intent_class"] == "workflow_process"
    assert snapshot["decision_timeline"][0]["phase"] == "planner_call"
    assert captured["usage"]["usage"]["planner_call"] is True


@pytest.mark.asyncio
async def test_trace_only_tool_planner_records_invalid_model_plan_without_execution():
    async def _chat_with_runtime_fallback(**kwargs):
        return (
            {
                "content": (
                    '{"version":1,"mode":"trace_only","intent_class":"workflow_process",'
                    '"confidence":0.7,"selected_tools":["bash"],"stop_criteria":["done"],"max_tool_calls":1}'
                ),
                "usage": {},
                "model": "planner-model",
            },
            {"provider_name": "test-provider", "model": "planner-model"},
            [{"status": "success"}],
        )

    snapshot = _context_snapshot()

    result = await maybe_call_trace_only_tool_planner(
        context_snapshot=snapshot,
        runtime_settings={PLANNER_ENABLED_SETTING: True},
        current_runtimes=[{"provider_name": "test-provider", "model": "planner-model"}],
        provider_reasoning_effort=None,
        request_timeout_seconds=30,
        chat_with_runtime_fallback=_chat_with_runtime_fallback,
        normalize_runtime_chat_result=_normalize,
        record_usage_event=_record_usage_event,
        db=None,
        session_id="session",
        user_id="user",
        request_id="request",
    )

    assert result["call_status"] == "completed"
    assert result["validation"]["valid"] is False
    assert result["validation"]["errors"] == ["selected_tool_not_in_catalog:bash"]
    assert snapshot["decision_timeline"][0]["status"] == "warning"


@pytest.mark.asyncio
async def test_trace_only_tool_planner_records_runtime_failure_as_warning():
    class _PlannerError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("planner unavailable")
            self.runtime_attempts = [{"status": "error", "error_class": "timeout"}]

    async def _chat_with_runtime_fallback(**kwargs):
        raise _PlannerError()

    snapshot = _context_snapshot()

    result = await maybe_call_trace_only_tool_planner(
        context_snapshot=snapshot,
        runtime_settings={PLANNER_ENABLED_SETTING: True},
        current_runtimes=[{"provider_name": "test-provider", "model": "planner-model"}],
        provider_reasoning_effort=None,
        request_timeout_seconds=30,
        chat_with_runtime_fallback=_chat_with_runtime_fallback,
        normalize_runtime_chat_result=_normalize,
        record_usage_event=_record_usage_event,
        db=None,
        session_id="session",
        user_id="user",
        request_id="request",
    )

    assert result["call_status"] == "failed"
    assert result["validation"]["errors"] == ["planner_call_failed"]
    assert snapshot["decision_timeline"][0]["metadata"]["attempt_count"] == 1
