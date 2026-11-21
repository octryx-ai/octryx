"""Focused runtime-attempt metadata tests for fallback error classification."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.engine import _chat_with_runtime_fallback


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_records_timeout_classification(monkeypatch):
    class HangingProvider:
        async def chat(self, **kwargs):
            await asyncio.sleep(3600)

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: HangingProvider())

    with pytest.raises(RuntimeError) as exc_info:
        await _chat_with_runtime_fallback(
            [
                {
                    "provider_name": "openrouter",
                    "api_key": "test",
                    "model": "stepfun/step-3.5-flash:free",
                    "max_runtime_retries": 0,
                }
            ],
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            request_timeout_seconds=0.01,
        )

    attempts = getattr(exc_info.value, "runtime_attempts", [])
    assert attempts[0]["error_class"] == "timeout"
    assert attempts[0]["retry_decision"] == "final_error"
    assert attempts[0]["attempt_stage"] == "chat"


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_records_provider_init_classification(monkeypatch):
    class GoodProvider:
        async def chat(self, **kwargs):
            return {"content": "recovered", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    def fake_get_provider(**kwargs):
        if kwargs.get("endpoint_url") == "http://broken.test":
            raise ValueError("misconfigured provider")
        return GoodProvider()

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "openai_compatible",
                "endpoint_url": "http://broken.test",
                "model": "broken",
                "target_id": "broken",
            },
            {
                "provider_name": "openai_compatible",
                "endpoint_url": "http://healthy.test",
                "model": "healthy",
                "target_id": "healthy",
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == "recovered"
    assert runtime["target_id"] == "healthy"
    assert attempts[0]["error_class"] == "provider_init"
    assert attempts[0]["retry_decision"] == "fallback_next_runtime"
    assert attempts[0]["attempt_stage"] == "provider_init"


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_records_context_retry_history(monkeypatch):
    call_count = {"count": 0}

    class RetryProvider:
        async def chat(self, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("context window exceeded")
            return {"content": "ok", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: RetryProvider())

    response, runtime, runtime_attempts = await _chat_with_runtime_fallback(
        [{"provider_name": "copilot", "api_key": "test", "model": "claude-haiku-4.5", "target_id": "ctx"}],
        messages=[
            {"role": "system", "content": "S" * 4000},
            {"role": "user", "content": "old " * 2000},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "current request"},
        ],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["target_id"] == "ctx"
    assert call_count["count"] == 2
    assert runtime_attempts[0]["error_class"] == "context_pressure"
    assert runtime_attempts[0]["retry_decision"] == "same_runtime_retry"
    assert runtime_attempts[1]["status"] == "success"
    assert runtime_attempts[1]["retry_history"] == [
        {
            "retry_index": 1,
            "error_class": "context_pressure",
            "retry_decision": "same_runtime_retry",
            "error": "context window exceeded",
        }
    ]
    assert runtime_attempts[1]["runtime_recovery"] == {
        "attempt_count": 2,
        "error_count": 1,
        "final_status": "success",
        "same_runtime_retry_count": 1,
        "error_classes": {"context_pressure": 1},
        "final_target_id": "ctx",
        "final_provider": "copilot",
        "final_model": "claude-haiku-4.5",
        "recovered": True,
    }
