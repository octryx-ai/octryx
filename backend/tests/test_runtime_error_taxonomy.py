"""Contract tests for the explicit runtime error taxonomy and fallback policy."""

import json

import pytest

from app.agent.runtime.retry_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    build_runtime_retry_policy,
)
from app.agent.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_DEFAULT,
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    CLASSIFICATION_SOURCE_EXPLICIT,
    CLASSIFICATION_SOURCE_MESSAGE_PATTERN,
    ProviderRuntimeError,
    classify_runtime_error,
)
from app.agent.runtime.runtime_fallback import _chat_with_runtime_fallback
from app.agent.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY


def test_explicit_provider_error_class_wins_over_message() -> None:
    exc = ProviderRuntimeError("rate limit exceeded", error_class="permanent", status_code=400)
    classification = classify_runtime_error(exc)
    assert classification.error_class == "permanent"
    assert classification.source == CLASSIFICATION_SOURCE_EXPLICIT


def test_provider_error_rejects_unknown_class() -> None:
    with pytest.raises(ValueError):
        ProviderRuntimeError("boom", error_class="not_a_class")


def test_timeout_type_classifies_without_message() -> None:
    classification = classify_runtime_error(TimeoutError())
    assert classification.error_class == "timeout"
    assert classification.source == CLASSIFICATION_SOURCE_EXCEPTION_TYPE


def test_connection_refused_type_is_unreachable() -> None:
    classification = classify_runtime_error(ConnectionRefusedError("x"))
    assert classification.error_class == "unreachable"
    assert classification.source == CLASSIFICATION_SOURCE_EXCEPTION_TYPE


def test_json_decode_error_is_malformed_response() -> None:
    try:
        json.loads("{nope")
    except json.JSONDecodeError as exc:
        classification = classify_runtime_error(exc)
    assert classification.error_class == "malformed_response"
    assert classification.source == CLASSIFICATION_SOURCE_EXCEPTION_TYPE


def test_message_pattern_fallback_is_marked_as_heuristic() -> None:
    classification = classify_runtime_error(RuntimeError("429 rate limit reached"))
    assert classification.error_class == "transient"
    assert classification.source == CLASSIFICATION_SOURCE_MESSAGE_PATTERN

    classification = classify_runtime_error(RuntimeError("prompt is too long for context window"))
    assert classification.error_class == "context_pressure"
    assert classification.source == CLASSIFICATION_SOURCE_MESSAGE_PATTERN


def test_unknown_error_defaults_to_permanent() -> None:
    classification = classify_runtime_error(RuntimeError("some provider-specific failure"))
    assert classification.error_class == "permanent"
    assert classification.source == CLASSIFICATION_SOURCE_DEFAULT


def test_provider_init_failures_are_classified_explicitly() -> None:
    classification = classify_runtime_error(RuntimeError("bad credentials"), provider_init=True)
    assert classification.error_class == "provider_init"


def test_retry_policy_parses_fallback_mode() -> None:
    # The resolved chain is part of the policy input: the per-driver fallback
    # default can only be applied when the caller names the chain.
    api_runtimes = [{"driver": "openrouter_api", "model": "primary"}]

    assert build_runtime_retry_policy({}, runtimes=api_runtimes)["fallback_mode"] == (
        RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
    )
    assert (
        build_runtime_retry_policy(
            {"runtime_fallback_mode": "First_Runtime_Only"}, runtimes=api_runtimes
        )["fallback_mode"]
        == RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
    )
    # An unknown stored value is not normalized into a governed mode: it keeps
    # the chain's default and is labelled as invalid.
    bogus = build_runtime_retry_policy({"runtime_fallback_mode": "bogus"}, runtimes=api_runtimes)
    assert bogus["fallback_mode"] == RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
    assert bogus["fallback_mode_source"] == "invalid_setting"


class _FakeClient:
    def __init__(self, behavior):
        self._behavior = behavior

    async def chat(self, **kwargs):
        outcome = self._behavior()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def close(self):
        return None


def _runtimes() -> list[dict]:
    return [
        {
            "provider_name": "primary",
            "model": "model-a",
            "target_id": "t1",
            "priority": 1,
            "max_runtime_retries": 0,
            "max_context_retries": 0,
            "max_malformed_retries": 0,
        },
        {
            "provider_name": "secondary",
            "model": "model-b",
            "target_id": "t2",
            "priority": 2,
            "max_runtime_retries": 0,
            "max_context_retries": 0,
            "max_malformed_retries": 0,
        },
    ]


def _factory(calls: list[str]):
    def factory(**client_kwargs):
        provider = str(client_kwargs.get("provider_name") or "")
        calls.append(provider)
        if provider == "primary":
            return _FakeClient(lambda: ProviderRuntimeError("primary down", error_class="permanent"))
        return _FakeClient(lambda: {"content": "ok", "tool_calls": []})

    return factory


@pytest.mark.asyncio
async def test_fallback_all_runtimes_reaches_second_runtime() -> None:
    calls: list[str] = []
    response, runtime, attempts = await _chat_with_runtime_fallback(
        _runtimes(),
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        get_provider_func=_factory(calls),
        retry_policy={"max_retries": 0, "pause_seconds": 0, "fallback_mode": RUNTIME_FALLBACK_MODE_ALL_RUNTIMES},
    )
    assert response["content"] == "ok"
    assert runtime["provider_name"] == "secondary"
    assert calls == ["primary", "secondary"]
    error_attempt = next(a for a in attempts if a.get("status") == "error")
    assert error_attempt["error_class"] == "permanent"
    assert error_attempt["error_class_source"] == CLASSIFICATION_SOURCE_EXPLICIT


@pytest.mark.asyncio
async def test_first_runtime_only_policy_denies_fallback() -> None:
    calls: list[str] = []
    with pytest.raises(RuntimeError) as excinfo:
        await _chat_with_runtime_fallback(
            _runtimes(),
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
            get_provider_func=_factory(calls),
            retry_policy={
                "max_retries": 0,
                "pause_seconds": 0,
                "fallback_mode": RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY,
            },
        )
    assert calls == ["primary"]
    attempts = excinfo.value.runtime_attempts
    denied = next(a for a in attempts if a.get("status") == "fallback_denied")
    assert denied["error_class"] == "fallback_denied_by_policy"
    assert "first_runtime_only" in denied["error"]
