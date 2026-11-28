"""Focused tests for runtime fallback retry planning."""

import pytest

from app.agent.runtime.retry_policy import (
    build_runtime_retry_policy,
    plan_exception_retry,
    plan_timeout_retry,
)


def test_build_runtime_retry_policy_clamps_invalid_values() -> None:
    policy = build_runtime_retry_policy(
        {
            "runtime_unreachable_retry_max_retries": "bad",
            "runtime_unreachable_retry_pause_seconds": -4,
        },
        runtimes=[{"driver": "openrouter_api", "model": "primary"}],
    )

    assert policy == {
        "max_retries": 2,
        "pause_seconds": 0,
        "fallback_mode": "all_runtimes",
        "fallback_mode_source": "default",
    }


def test_build_runtime_retry_policy_preserves_explicit_positive_values() -> None:
    policy = build_runtime_retry_policy(
        {
            "runtime_unreachable_retry_max_retries": "5",
            "runtime_unreachable_retry_pause_seconds": 9,
        },
        runtimes=[{"driver": "openrouter_api", "model": "primary"}],
    )

    assert policy == {
        "max_retries": 5,
        "pause_seconds": 9,
        "fallback_mode": "all_runtimes",
        "fallback_mode_source": "default",
    }


def test_plan_timeout_retry_prefers_same_runtime_without_fallbacks() -> None:
    plan = plan_timeout_retry(
        has_additional_runtimes=False,
        transient_retries_remaining=1,
        retry_index=0,
    )

    assert plan.retry_decision == "same_runtime_retry"
    assert plan.should_retry is True
    assert plan.sleep_seconds == 0.1


def test_plan_exception_retry_retries_same_runtime_first_for_transient_errors() -> None:
    # A transient flake on the selected runtime must not immediately dump the
    # run onto a (possibly much weaker) fallback runtime — one cheap
    # same-runtime retry comes first, fallback only after the budget is spent.
    plan = plan_exception_retry(
        error_class="transient",
        has_additional_runtimes=True,
        transient_retries_remaining=1,
        context_retries_remaining=0,
        malformed_retries_remaining=0,
        attempt_messages=[{"role": "user", "content": "hello"}],
        attempt_max_tokens=1024,
        default_max_tokens=1024,
        retry_index=0,
        context_pressure_retry_messages=lambda messages: messages,
    )

    assert plan.retry_decision == "same_runtime_retry"
    assert plan.should_retry is True

    exhausted = plan_exception_retry(
        error_class="transient",
        has_additional_runtimes=True,
        transient_retries_remaining=0,
        context_retries_remaining=0,
        malformed_retries_remaining=0,
        attempt_messages=[{"role": "user", "content": "hello"}],
        attempt_max_tokens=1024,
        default_max_tokens=1024,
        retry_index=1,
        context_pressure_retry_messages=lambda messages: messages,
    )
    assert exhausted.retry_decision == "fallback_next_runtime"
    assert exhausted.should_retry is False

    timeout_plan = plan_exception_retry(
        error_class="timeout",
        has_additional_runtimes=True,
        transient_retries_remaining=1,
        context_retries_remaining=0,
        malformed_retries_remaining=0,
        attempt_messages=[{"role": "user", "content": "hello"}],
        attempt_max_tokens=1024,
        default_max_tokens=1024,
        retry_index=0,
        context_pressure_retry_messages=lambda messages: messages,
    )
    assert timeout_plan.retry_decision == "fallback_next_runtime"


def test_plan_exception_retry_reduces_context_payload_before_retry() -> None:
    original_messages = [{"role": "user", "content": "x" * 4000}]
    trimmed_messages = [{"role": "user", "content": "trimmed"}]

    plan = plan_exception_retry(
        error_class="context_pressure",
        has_additional_runtimes=False,
        transient_retries_remaining=0,
        context_retries_remaining=1,
        malformed_retries_remaining=0,
        attempt_messages=original_messages,
        attempt_max_tokens=2000,
        default_max_tokens=2000,
        retry_index=0,
        context_pressure_retry_messages=lambda messages: trimmed_messages,
    )

    assert plan.retry_decision == "same_runtime_retry"
    assert plan.should_retry is True
    assert plan.next_messages == trimmed_messages
    assert plan.next_max_tokens == 1500


def test_plan_exception_retry_retries_malformed_response_without_fallbacks() -> None:
    plan = plan_exception_retry(
        error_class="malformed_response",
        has_additional_runtimes=False,
        transient_retries_remaining=0,
        context_retries_remaining=0,
        malformed_retries_remaining=1,
        attempt_messages=[{"role": "user", "content": "hello"}],
        attempt_max_tokens=1024,
        default_max_tokens=1024,
        retry_index=1,
        context_pressure_retry_messages=lambda messages: messages,
    )

    assert plan.retry_decision == "same_runtime_retry"
    assert plan.should_retry is True
    assert plan.sleep_seconds == 0.1


def test_build_runtime_retry_policy_requires_the_resolved_runtime_chain() -> None:
    with pytest.raises(TypeError):
        build_runtime_retry_policy({})  # type: ignore[call-arg]
