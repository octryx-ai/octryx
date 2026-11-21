"""Runtime fallback records its decision for a transient error and retries the full runtime chain when every runtime is unreachable, except for tool runs."""

from __future__ import annotations

import httpx
import pytest

from app.agent.engine import _chat_with_runtime_fallback


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_records_fallback_decision_for_transient_error(monkeypatch):
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
            {
                "provider_name": "openrouter",
                "api_key": "primary-key",
                "model": "primary-model",
                "target_id": "primary",
            },
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
    # Retry before fallback: a transient error gets one cheap same-runtime retry before the
    # chain falls back, so a provider hiccup does not drop the run to a weaker model.
    assert attempts == [
        ("primary", "primary-model"),
        ("primary", "primary-model"),
        ("fallback", "fallback-model"),
    ]
    assert runtime_attempts[0]["error_class"] == "transient"
    assert runtime_attempts[0]["retry_decision"] == "same_runtime_retry"
    assert runtime_attempts[1]["error_class"] == "transient"
    assert runtime_attempts[1]["retry_decision"] == "fallback_next_runtime"
    assert runtime_attempts[2]["runtime_recovery"] == {
        "attempt_count": 3,
        "error_count": 2,
        "final_status": "success",
        "fallback_count": 1,
        "error_classes": {"transient": 2},
        "same_runtime_retry_count": 1,
        "final_target_id": "fallback",
        "final_provider": "openrouter",
        "final_model": "fallback-model",
        "recovered": True,
    }


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_retries_full_runtime_chain_when_all_runtimes_unreachable(monkeypatch):
    sleep_calls: list[float] = []

    class UnreachableProvider:
        def __init__(self, label: str) -> None:
            self.label = label

        async def chat(self, **kwargs):
            raise httpx.ConnectError("connection refused")

        async def close(self):
            return None

    def fake_get_provider(**kwargs):
        return UnreachableProvider(str(kwargs.get("api_key") or "unknown"))

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)
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
            retry_policy={"max_retries": 2, "pause_seconds": 4},
        )

    runtime_attempts = getattr(exc_info.value, "runtime_attempts", [])
    error_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "error"]
    retry_wait_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "retry_wait"]

    assert [attempt["retry_cycle_index"] for attempt in error_attempts] == [0, 0, 1, 1, 2, 2]
    assert [attempt["error_class"] for attempt in error_attempts] == ["unreachable"] * 6
    assert [attempt["retry_cycle_index"] for attempt in retry_wait_attempts] == [0, 1]
    assert all(attempt["retry_decision"] == "retry_all_runtimes" for attempt in retry_wait_attempts)
    assert sleep_calls == [4, 4]


@pytest.mark.asyncio
async def test_chat_with_runtime_fallback_skips_full_chain_retries_for_tool_runs(monkeypatch):
    sleep_calls: list[float] = []

    class UnreachableProvider:
        async def chat(self, **kwargs):
            raise httpx.ConnectError("connection refused")

        async def close(self):
            return None

    def fake_get_provider(**kwargs):
        return UnreachableProvider()

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    monkeypatch.setattr("app.agent.engine.get_provider", fake_get_provider)
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
            tools=[{"type": "function", "function": {"name": "code_search"}}],
            request_timeout_seconds=5,
            retry_policy={"max_retries": 2, "pause_seconds": 4},
        )

    runtime_attempts = getattr(exc_info.value, "runtime_attempts", [])
    error_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "error"]
    retry_wait_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "retry_wait"]

    assert [attempt["retry_cycle_index"] for attempt in error_attempts] == [0, 0]
    assert [attempt["error_class"] for attempt in error_attempts] == ["unreachable", "unreachable"]
    assert retry_wait_attempts == []
    assert sleep_calls == []
