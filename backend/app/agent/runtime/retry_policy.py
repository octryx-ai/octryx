"""Retry planning helpers for runtime fallback attempts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypedDict

from app.agent.runtime.runtime_errors import NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES
from app.agent.runtime.runtime_fallback_policy import (
    FALLBACK_MODE_SOURCE_DEFAULT,
    FALLBACK_MODE_SOURCE_GOVERNED_SETTING,
    FALLBACK_MODE_SOURCE_INVALID_SETTING,
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RUNTIME_FALLBACK_MODES,
)

DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES = 2
DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS = 3

RuntimeMessage: TypeAlias = dict[str, Any]
RuntimeRetryDecision = Literal["same_runtime_retry", "fallback_next_runtime", "final_error"]


class RuntimeRetryPolicy(TypedDict):
    max_retries: int
    pause_seconds: float
    fallback_mode: str
    fallback_mode_source: str


def build_runtime_retry_policy(
    runtime_settings: dict[str, Any],
    *,
    runtimes: list[RuntimeMessage] | None,
) -> RuntimeRetryPolicy:
    try:
        max_retries = int(
            runtime_settings.get("runtime_unreachable_retry_max_retries")
            or DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES
        )
    except (TypeError, ValueError):
        max_retries = DEFAULT_RUNTIME_UNREACHABLE_RETRY_MAX_RETRIES
    try:
        pause_seconds = int(
            runtime_settings.get("runtime_unreachable_retry_pause_seconds")
            or DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS
        )
    except (TypeError, ValueError):
        pause_seconds = DEFAULT_RUNTIME_UNREACHABLE_RETRY_PAUSE_SECONDS
    # The stored value arrives raw. An unknown value is recorded as invalid rather than silently accepted, so
    # the evidence stays honest. Unset means "try the next allowed model" for every driver:
    # the chain is bounded by the Workspace allowlist and the data clearance, so there is no per-driver default.
    configured_mode = str(runtime_settings.get("runtime_fallback_mode") or "").strip().lower()
    if configured_mode in RUNTIME_FALLBACK_MODES:
        fallback_mode = configured_mode
        fallback_mode_source = FALLBACK_MODE_SOURCE_GOVERNED_SETTING
    else:
        fallback_mode = RUNTIME_FALLBACK_MODE_ALL_RUNTIMES
        fallback_mode_source = (
            FALLBACK_MODE_SOURCE_INVALID_SETTING if configured_mode else FALLBACK_MODE_SOURCE_DEFAULT
        )
    return {
        "max_retries": max(0, max_retries),
        "pause_seconds": max(0, pause_seconds),
        "fallback_mode": fallback_mode,
        "fallback_mode_source": fallback_mode_source,
    }


@dataclass(frozen=True)
class RuntimeRetryPlan:
    retry_decision: RuntimeRetryDecision
    should_retry: bool = False
    sleep_seconds: float = 0.0
    next_messages: list[RuntimeMessage] | None = None
    next_max_tokens: int | None = None


def plan_timeout_retry(
    *,
    has_additional_runtimes: bool,
    transient_retries_remaining: int,
    retry_index: int,
) -> RuntimeRetryPlan:
    if transient_retries_remaining > 0 and not has_additional_runtimes:
        return RuntimeRetryPlan(
            retry_decision="same_runtime_retry",
            should_retry=True,
            sleep_seconds=min(0.5, 0.1 * (retry_index + 1)),
        )
    if has_additional_runtimes:
        return RuntimeRetryPlan(retry_decision="fallback_next_runtime")
    return RuntimeRetryPlan(retry_decision="final_error")


def plan_exception_retry(
    *,
    error_class: str,
    has_additional_runtimes: bool,
    transient_retries_remaining: int,
    context_retries_remaining: int,
    malformed_retries_remaining: int,
    attempt_messages: list[RuntimeMessage],
    attempt_max_tokens: int,
    default_max_tokens: int,
    retry_index: int,
    context_pressure_retry_messages: Callable[[list[RuntimeMessage]], list[RuntimeMessage]],
) -> RuntimeRetryPlan:
    if error_class in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES:
        # A denied alias or a violated model group is a governance outcome.
        # Retrying it or moving to another runtime would turn an explicit
        # failure into a silent substitution.
        return RuntimeRetryPlan(retry_decision="final_error")
    if error_class == "context_pressure" and context_retries_remaining > 0:
        trimmed_messages = context_pressure_retry_messages(attempt_messages)
        reduced_max_tokens = max(256, int((attempt_max_tokens or default_max_tokens or 4096) * 0.75))
        if trimmed_messages != attempt_messages or reduced_max_tokens != attempt_max_tokens:
            return RuntimeRetryPlan(
                retry_decision="same_runtime_retry",
                should_retry=True,
                next_messages=trimmed_messages,
                next_max_tokens=reduced_max_tokens,
            )
    elif error_class == "malformed_response" and malformed_retries_remaining > 0 and not has_additional_runtimes:
        return RuntimeRetryPlan(
            retry_decision="same_runtime_retry",
            should_retry=True,
            sleep_seconds=min(0.25, 0.05 * (retry_index + 1)),
        )
    elif error_class == "transient" and transient_retries_remaining > 0:
        # A transient error on the selected runtime gets one cheap same-runtime
        # retry BEFORE falling back, even when fallback runtimes exist: the
        # fallback chain may end at a much weaker model, and a provider hiccup
        # (such as a one-off model_not_supported for a model that served the
        # previous request) must not lower the run's model quality.
        return RuntimeRetryPlan(
            retry_decision="same_runtime_retry",
            should_retry=True,
            sleep_seconds=min(0.5, 0.1 * (retry_index + 1)),
        )
    elif error_class == "timeout" and transient_retries_remaining > 0 and not has_additional_runtimes:
        # Timeouts stay fallback-first when alternatives exist — retrying a
        # timed-out runtime costs the full request duration again.
        return RuntimeRetryPlan(
            retry_decision="same_runtime_retry",
            should_retry=True,
            sleep_seconds=min(0.5, 0.1 * (retry_index + 1)),
        )

    if has_additional_runtimes:
        return RuntimeRetryPlan(retry_decision="fallback_next_runtime")
    return RuntimeRetryPlan(retry_decision="final_error")
