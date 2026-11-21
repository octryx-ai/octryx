"""Runtime regression pack: every runtime is retried before a clear unreachable error, and a malformed primary response falls back to the next runtime."""

from __future__ import annotations

import httpx
import pytest

from app.agent.engine import _chat_with_runtime_fallback


@pytest.mark.asyncio
async def test_runtime_regression_pack_retries_all_runtimes_then_raises_clear_unreachable_error(monkeypatch):
    sleep_calls: list[float] = []

    class UnreachableProvider:
        async def chat(self, **kwargs):
            raise httpx.ConnectError("connection refused")

        async def close(self):
            return None

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: UnreachableProvider())
    monkeypatch.setattr("app.agent.engine.runtime._engine_runtime_fallback.asyncio.sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="No runtime is currently reachable") as exc_info:
        await _chat_with_runtime_fallback(
            [
                {
                    "provider_name": "openrouter",
                    "api_key": "primary",
                    "model": "primary-model",
                    "target_id": "primary",
                    "max_runtime_retries": 0,
                },
                {
                    "provider_name": "openrouter",
                    "api_key": "fallback",
                    "model": "fallback-model",
                    "target_id": "fallback",
                    "max_runtime_retries": 0,
                },
            ],
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            request_timeout_seconds=5,
            retry_policy={"max_retries": 1, "pause_seconds": 3},
        )

    runtime_attempts = getattr(exc_info.value, "runtime_attempts", [])
    error_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "error"]
    retry_wait_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "retry_wait"]

    assert [attempt["target_id"] for attempt in error_attempts] == [
        "primary",
        "fallback",
        "primary",
        "fallback",
    ]
    assert [attempt["retry_cycle_index"] for attempt in error_attempts] == [0, 0, 1, 1]
    assert all(attempt["error_class"] == "unreachable" for attempt in error_attempts)
    assert retry_wait_attempts == [
        {
            "provider": "runtime-fallback",
            "model": "retry-loop",
            "status": "retry_wait",
            "retry_cycle_index": 0,
            "retry_decision": "retry_all_runtimes",
            "sleep_seconds": 3.0,
            "error_class": "all_runtimes_unreachable",
            "error": "all configured runtimes were unreachable or non-responsive in this retry cycle",
        }
    ]
    assert sleep_calls == [3.0]


@pytest.mark.asyncio
async def test_runtime_regression_pack_falls_back_after_malformed_primary_response(monkeypatch):
    call_order: list[str] = []

    class PrimaryProvider:
        async def chat(self, **kwargs):
            call_order.append("primary")
            raise RuntimeError("OpenAI-compatible API returned invalid response payload: malformed choice")

        async def close(self):
            return None

    class FallbackProvider:
        async def chat(self, **kwargs):
            call_order.append("fallback")
            return {"content": "recovered", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    def fake_get_provider(**kwargs):
        return PrimaryProvider() if kwargs.get("api_key") == "primary-key" else FallbackProvider()

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)

    response, runtime, runtime_attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "openai_compatible",
                "endpoint_url": "http://broken.test",
                "api_key": "primary-key",
                "model": "broken",
                "target_id": "primary",
            },
            {
                "provider_name": "openai_compatible",
                "endpoint_url": "http://healthy.test",
                "api_key": "fallback-key",
                "model": "healthy",
                "target_id": "fallback",
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert call_order == ["primary", "fallback"]
    assert response["content"] == "recovered"
    assert runtime["target_id"] == "fallback"
    assert runtime_attempts[0]["error_class"] == "malformed_response"
    assert runtime_attempts[0]["retry_decision"] == "fallback_next_runtime"
    assert runtime_attempts[1]["status"] == "success"
