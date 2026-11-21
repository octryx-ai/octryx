"""Chat with runtime fallback on Ollama thinking and token budgets, tool-turn runtime skips and request duration metrics."""

from typing import Any

import pytest

from app.agent.engine import _chat_with_runtime_fallback


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_does_not_auto_enable_ollama_thinking_for_gemma(monkeypatch):
    captured_kwargs: dict[str, Any] = {}

    class InspectingProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    def _fake_get_provider(**kwargs):
        captured_kwargs.update(kwargs)
        return InspectingProvider()

    monkeypatch.setattr("app.agent.engine.get_provider", _fake_get_provider)

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "ollama",
                "driver": "ollama",
                "endpoint_url": "http://localhost:11434",
                "config_json": {"request_timeout_seconds": 180},
                "model": "gemma4:e4b",
            }
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        reasoning_effort="low",
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["provider_name"] == "ollama"
    assert attempts[0]["status"] == "success"
    assert "think" not in captured_kwargs["config_json"]
    assert int(attempts[0]["duration_ms"]) >= 0


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_respects_explicit_ollama_think_override(monkeypatch):
    captured_kwargs: dict[str, Any] = {}

    class InspectingProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    def _fake_get_provider(**kwargs):
        captured_kwargs.update(kwargs)
        return InspectingProvider()

    monkeypatch.setattr("app.agent.engine.get_provider", _fake_get_provider)

    await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "ollama",
                "driver": "ollama",
                "endpoint_url": "http://localhost:11434",
                "config_json": {"request_timeout_seconds": 180, "think": False},
                "model": "gemma4:e4b",
            }
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        reasoning_effort="high",
        request_timeout_seconds=5,
    )

    assert captured_kwargs["config_json"]["think"] is False


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_increases_ollama_token_budget_for_thinking(monkeypatch):
    captured_chat_kwargs: dict[str, Any] = {}

    class InspectingProvider:
        async def chat(self, **kwargs):
            captured_chat_kwargs.update(kwargs)
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: InspectingProvider())

    await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "ollama",
                "driver": "ollama",
                "endpoint_url": "http://localhost:11434",
                "config_json": {"request_timeout_seconds": 180},
                "model": "gemma4:e4b",
                "max_tokens_per_request": 512,
            }
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        reasoning_effort="low",
        request_timeout_seconds=5,
    )

    assert captured_chat_kwargs["max_tokens"] == 1024


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_skips_ollama_gemma_for_tool_turns(monkeypatch):
    class FastProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: FastProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "ollama",
                "driver": "ollama",
                "endpoint_url": "http://localhost:11434",
                "config_json": {"request_timeout_seconds": 180},
                "model": "gemma4:e4b",
            },
            {
                "provider_name": "copilot",
                "driver": "copilot",
                "api_key": "test",
                "model": "gpt-4o",
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "demo_tool", "parameters": {"type": "object"}}}],
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["provider_name"] == "copilot"
    assert attempts[0]["provider"] == "ollama"
    assert attempts[0]["status"] == "skipped"
    assert "does not support requested tool calls" in str(attempts[0]["error"])


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_skips_runtime_marked_without_tool_support(monkeypatch):
    class FastProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: FastProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [
            {
                "provider_name": "bedrock",
                "driver": "bedrock_api",
                "model": "amazon.nova-micro-v1:0",
                "supports_tools": False,
            },
            {
                "provider_name": "bedrock",
                "driver": "bedrock_api",
                "model": "amazon.nova-2-lite-v1:0",
                "supports_tools": True,
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=[{"type": "function", "function": {"name": "demo_tool", "parameters": {"type": "object"}}}],
        request_timeout_seconds=5,
    )

    assert response["content"] == "ok"
    assert runtime["model"] == "amazon.nova-2-lite-v1:0"
    assert attempts[0]["model"] == "amazon.nova-micro-v1:0"
    assert attempts[0]["status"] == "skipped"
    assert "does not support requested tool calls" in str(attempts[0]["error"])


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_records_generic_request_duration(monkeypatch):
    class FastProvider:
        async def chat(self, **kwargs):
            return {
                "content": "ok",
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": kwargs["model"],
            }

        async def close(self):
            return None

    monkeypatch.setattr("app.agent.engine.get_provider", lambda **kwargs: FastProvider())

    response, runtime, attempts = await _chat_with_runtime_fallback(
        [{"provider_name": "openrouter", "model": "demo-model"}],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=5,
    )

    assert runtime["provider_name"] == "openrouter"
    assert int(response["usage"]["request_duration_ms"]) >= 0
    assert int(attempts[0]["duration_ms"]) >= 0
