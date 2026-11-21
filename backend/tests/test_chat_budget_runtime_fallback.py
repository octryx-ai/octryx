"""Chat with runtime fallback: request timeouts and empty assistant outputs."""

import asyncio

import pytest

import app.agent.engine as engine_module


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_honors_request_timeout(monkeypatch):
    class SlowClient:
        async def chat(self, **kwargs):
            await asyncio.sleep(0.05)
            return {"content": "late", "tool_calls": [], "usage": {}}

        async def close(self):
            return None

    monkeypatch.setattr(engine_module, "get_provider", lambda **kwargs: SlowClient())

    with pytest.raises(RuntimeError) as exc_info:
        await engine_module._chat_with_runtime_fallback(
            [
                {
                    "provider_name": "copilot",
                    "model": "claude-haiku-4.5",
                    "api_key": None,
                    "priority": 1,
                    "target_id": "target-1",
                }
            ],
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            request_timeout_seconds=0.01,
        )

    assert "request timed out" in str(exc_info.value)
    attempts = getattr(exc_info.value, "runtime_attempts", [])
    assert attempts
    assert attempts[0]["status"] == "error"
    assert "timed out" in attempts[0]["error"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_skips_empty_assistant_output(monkeypatch):
    class EmptyThenUsefulClient:
        calls = 0

        async def chat(self, **kwargs):
            type(self).calls += 1
            if type(self).calls == 1:
                return {"content": "", "tool_calls": [], "usage": {}}
            return {"content": "usable", "tool_calls": [], "usage": {}}

        async def close(self):
            return None

    monkeypatch.setattr(engine_module, "get_provider", lambda **kwargs: EmptyThenUsefulClient())

    response, runtime, attempts = await engine_module._chat_with_runtime_fallback(
        [
            {
                "provider_name": "ollama",
                "model": "gemma4:e4b",
                "api_key": None,
                "priority": 1,
                "target_id": "target-empty",
            },
            {
                "provider_name": "openrouter",
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "api_key": "test",
                "priority": 2,
                "target_id": "target-useful",
            },
        ],
        messages=[{"role": "user", "content": "hello"}],
        tools=None,
        request_timeout_seconds=1,
    )

    assert response["content"] == "usable"
    assert runtime["target_id"] == "target-useful"
    assert [attempt["target_id"] for attempt in attempts] == ["target-empty", "target-useful"]
    assert attempts[0]["status"] == "error"
    assert attempts[0]["empty_assistant_output"] is True
    assert attempts[1]["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_errors_when_all_outputs_empty(monkeypatch):
    class EmptyClient:
        async def chat(self, **kwargs):
            return {"content": "", "tool_calls": [], "usage": {}}

        async def close(self):
            return None

    monkeypatch.setattr(engine_module, "get_provider", lambda **kwargs: EmptyClient())

    with pytest.raises(RuntimeError) as exc_info:
        await engine_module._chat_with_runtime_fallback(
            [
                {
                    "provider_name": "ollama",
                    "model": "gemma4:e4b",
                    "api_key": None,
                    "priority": 1,
                    "target_id": "target-empty",
                }
            ],
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
            request_timeout_seconds=1,
        )

    assert "empty assistant output without tool calls" in str(exc_info.value)
    attempts = getattr(exc_info.value, "runtime_attempts", [])
    assert attempts[0]["status"] == "error"
    assert attempts[0]["empty_assistant_output"] is True
