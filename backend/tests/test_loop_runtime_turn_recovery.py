"""execute_runtime_turn records runtime recovery in snapshots and error traces and explains an unreachable runtime."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.loops.runtime._loop_runtime_turn import execute_runtime_turn
from app.agent.loops.runtime._loop_runtime_turn_inputs import RuntimeTurnInputs
from tests.loop_runtime_turn_support import build_runtime_turn_kwargs


@pytest.mark.asyncio
async def test_execute_runtime_turn_adds_runtime_recovery_to_context_snapshot_on_success():
    captured: dict[str, Any] = {}

    async def _dispatch_loop_runtime_response(**kwargs):
        return (
            {
                "content": "ok",
                "tool_calls": [],
                "model": "fallback-model",
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
            {"provider_name": "openrouter", "model": "fallback-model", "target_id": "fallback"},
            [
                {
                    "provider": "openrouter",
                    "model": "primary-model",
                    "target_id": "primary",
                    "status": "error",
                    "error_class": "transient",
                    "retry_decision": "fallback_next_runtime",
                },
                {
                    "provider": "openrouter",
                    "model": "fallback-model",
                    "target_id": "fallback",
                    "status": "success",
                },
            ],
            None,
        )

    async def _persist_runtime_assistant_response(**kwargs):
        captured["context_snapshot"] = kwargs["context_snapshot"]
        captured["runtime_attempts"] = kwargs["runtime_attempts"]
        return {"id": "assistant"}, {"id": "trace"}

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["persist_runtime_assistant_response"] = _persist_runtime_assistant_response

    result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))

    assert result["action"] == "ok"
    assert captured["context_snapshot"]["runtime_recovery"] == {
        "attempt_count": 2,
        "error_count": 1,
        "final_status": "success",
        "fallback_count": 1,
        "error_classes": {"transient": 1},
        "final_target_id": "fallback",
        "final_provider": "openrouter",
        "final_model": "fallback-model",
        "recovered": True,
    }
    assert captured["runtime_attempts"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_execute_runtime_turn_persists_runtime_recovery_in_error_trace():
    captured: dict[str, Any] = {}

    class _RuntimeError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("runtime failed")
            self.runtime_attempts = [
                {
                    "provider": "copilot",
                    "model": "claude-haiku-4.5",
                    "target_id": "ctx",
                    "status": "error",
                    "error_class": "context_pressure",
                    "retry_decision": "same_runtime_retry",
                },
                {
                    "provider": "copilot",
                    "model": "claude-haiku-4.5",
                    "target_id": "ctx",
                    "status": "error",
                    "error_class": "context_pressure",
                    "retry_decision": "final_error",
                },
            ]

    async def _dispatch_loop_runtime_response(**kwargs):
        raise _RuntimeError()

    async def _persist_traced_assistant_message(**kwargs):
        captured.update(kwargs)
        return None

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["persist_traced_assistant_message"] = _persist_traced_assistant_message

    result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))

    assert result["action"] == "error"
    assert captured["context_snapshot"]["runtime_recovery"] == {
        "attempt_count": 2,
        "error_count": 2,
        "final_status": "error",
        "same_runtime_retry_count": 1,
        "error_classes": {"context_pressure": 2},
        "final_target_id": "ctx",
        "final_provider": "copilot",
        "final_model": "claude-haiku-4.5",
    }
    assert captured["raw_output"]["runtime_recovery"] == captured["context_snapshot"]["runtime_recovery"]


@pytest.mark.asyncio
async def test_execute_runtime_turn_uses_clear_message_when_no_runtime_is_reachable():
    captured: dict[str, Any] = {}

    class _RuntimeError(RuntimeError):
        def __init__(self) -> None:
            super().__init__("No runtime is currently reachable.")
            self.runtime_attempts = [
                {
                    "provider": "openrouter",
                    "model": "primary-model",
                    "target_id": "primary",
                    "status": "error",
                    "error_class": "unreachable",
                    "retry_cycle_index": 0,
                },
                {
                    "provider": "openrouter",
                    "model": "fallback-model",
                    "target_id": "fallback",
                    "status": "error",
                    "error_class": "timeout",
                    "retry_cycle_index": 0,
                },
            ]

    async def _dispatch_loop_runtime_response(**kwargs):
        raise _RuntimeError()

    async def _persist_traced_assistant_message(**kwargs):
        captured.update(kwargs)
        return None

    kwargs = build_runtime_turn_kwargs()
    kwargs["dispatch_loop_runtime_response"] = _dispatch_loop_runtime_response
    kwargs["persist_traced_assistant_message"] = _persist_traced_assistant_message

    result = await execute_runtime_turn(RuntimeTurnInputs(**kwargs))

    assert result["action"] == "error"
    assert result["event"]["content"] == "No runtime is currently reachable. Please try again later."
    assert captured["content"] == "No runtime is currently reachable. Please try again later."
