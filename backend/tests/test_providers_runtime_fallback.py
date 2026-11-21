"""Chat with runtime fallback: timeouts, empty or blank output, cache scope, init errors and retries before falling back."""

import asyncio
from typing import Any

import pytest

from app.agent.engine import _chat_with_runtime_fallback


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_times_out(monkeypatch):
    class HangingProvider:
        async def chat(self, **kwargs):
            await asyncio.sleep(3600)

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: HangingProvider())

    with pytest.raises(RuntimeError) as exc_info:
        await _chat_with_runtime_fallback(
            [{"provider_name": "openrouter", "api_key": "test", "model": "stepfun/step-3.5-flash:free"}],
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            request_timeout_seconds=0.01,
        )

    message = str(exc_info.value)
    assert "All configured runtime targets failed" in message
    assert "request timed out" in message


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_returns_empty_provider_output_to_loop(monkeypatch):
    class EmptyProvider:
        async def chat(self, **kwargs):
            return {
                "content": "",
                "tool_calls": [],
                "usage": {"completion_tokens": 129},
                "model": "claude-haiku-4.5",
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: EmptyProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [{"provider_name": "copilot", "api_key": "test", "model": "claude-haiku-4.5"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == ""
    assert response["tool_calls"] == []
    assert response["empty_assistant_output"] is True
    assert runtime["provider_name"] == "copilot"
    assert attempts[0]["status"] == "success"
    assert attempts[0]["empty_assistant_output"] is True
    assert int(attempts[0]["duration_ms"]) >= 0
    assert int(response["usage"]["request_duration_ms"]) >= 0


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_preserves_runtime_model_when_provider_returns_blank(monkeypatch):
    class BlankModelProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "",
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: BlankModelProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [{"provider_name": "bedrock", "model": "anthropic.claude-sonnet-4-6"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert response["model"] == "anthropic.claude-sonnet-4-6"
    assert runtime["provider_name"] == "bedrock"
    assert attempts[0]["status"] == "success"


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_strips_cache_scope_for_non_bedrock(monkeypatch):
    captured: dict[str, Any] = {}

    class CapturingProvider:
        async def chat(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return {"content": "ok", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: CapturingProvider())

    await _chat_with_runtime_fallback(
        [{"provider_name": "openrouter", "api_key": "test", "model": "model"}],
        messages=[
            {"role": "system", "content": "Stable", "cache_scope": "stable"},
            {"role": "user", "content": "hello"},
        ],
        tools=None,
        request_timeout_seconds=5,
    )

    assert captured["messages"][0] == {"role": "system", "content": "Stable"}


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_continues_after_provider_init_error(monkeypatch):
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
    assert attempts[0]["status"] == "error"
    assert "misconfigured provider" in attempts[0]["error"]
    assert attempts[1]["status"] == "success"


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_retries_context_pressure_once(monkeypatch):
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
    assert runtime_attempts[0]["status"] == "error"
    assert "context window exceeded" in runtime_attempts[0]["error"]
    assert runtime_attempts[1]["status"] == "success"


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_retries_transient_once_on_same_runtime_before_fallback(monkeypatch):
    attempts: list[tuple[str, str]] = []

    class RetryProvider:
        def __init__(self, label: str) -> None:
            self.label = label

        async def chat(self, **kwargs):
            attempts.append((self.label, kwargs["model"]))
            if self.label == "primary":
                raise RuntimeError("rate limited")
            return {"content": "ok", "tool_calls": [], "usage": {}, "model": kwargs["model"]}

        async def close(self):
            return None

    def fake_get_provider(**kwargs):
        api_key = str(kwargs.get("api_key") or "")
        return RetryProvider("primary" if api_key == "primary-key" else "fallback")

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)

    response, runtime, runtime_attempts = await _chat_with_runtime_fallback(
        [
            {"provider_name": "openrouter", "api_key": "primary-key", "model": "primary-model", "target_id": "primary"},
            {
                "provider_name": "openrouter",
                "api_key": "fallback-key",
                "model": "fallback-model",
                "target_id": "fallback",
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["target_id"] == "fallback"
    # One cheap same-runtime retry for a transient error, then fallback.
    assert attempts == [
        ("primary", "primary-model"),
        ("primary", "primary-model"),
        ("fallback", "fallback-model"),
    ]
    assert [attempt["status"] for attempt in runtime_attempts] == ["error", "error", "success"]
