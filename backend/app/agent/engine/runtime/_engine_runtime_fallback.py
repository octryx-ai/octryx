"""Runtime selection and fallback chat helpers for the engine."""

import asyncio
import inspect
import math
import time
from collections.abc import Callable
from typing import Any

from app.agent.core.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY

from ....services.content_routing.notices import attach_to_attempt as attach_content_notice
from ...core.runtime.runtime_admission_contract import runtime_admission_denial
from ...core.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES,
    classify_runtime_error,
)
from ...core.turn.runtime_recovery_telemetry import attach_runtime_recovery_telemetry
from ...core.types import AgentResponse, RuntimeTarget
from ...providers import get_provider as _default_get_provider
from ..messages._engine_message_helpers import _estimate_message_tokens, _trim_messages_to_budget
from ._engine_runtime_admission import (
    CHAIN_HALT_ERROR_CLASS,
    record_admission_denial,
    record_chain_halt,
)
from ._engine_runtime_attempts import _build_runtime_attempt, _record_retry_history
from ._engine_runtime_retry_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RuntimeRetryPolicy,
    plan_exception_retry,
    plan_timeout_retry,
)


def _runtime_client_kwargs_for_turn(runtime: dict[str, Any], *, reasoning_effort: str | None) -> dict[str, Any]:
    client_kwargs = {
        key: value
        for key, value in runtime.items()
        if key
        not in {
            "provider_id",
            "target_id",
            "priority",
            "model",
            "supports_tools",
            "supports_vision",
            "max_tokens_per_request",
            "request_timeout_seconds",
        }
    }
    config_json = client_kwargs.get("config_json")
    if not isinstance(config_json, dict):
        return client_kwargs
    if str(client_kwargs.get("driver") or client_kwargs.get("provider_name") or "").strip().lower() != "ollama":
        return client_kwargs
    if "think" in config_json:
        return client_kwargs
    model_id = str(runtime.get("model") or runtime.get("model_id") or "").strip().lower()
    if "gemma" in model_id:
        return client_kwargs
    client_kwargs["config_json"] = {
        **config_json,
        "think": bool(reasoning_effort),
    }
    return client_kwargs


def _runtime_max_tokens_for_turn(runtime: dict[str, Any], *, max_tokens: int, reasoning_effort: str | None) -> int:
    resolved_max_tokens = int(runtime.get("max_tokens_per_request") or max_tokens)
    runtime_driver = str(runtime.get("driver") or runtime.get("provider_name") or "").strip().lower()
    config_json = runtime.get("config_json") if isinstance(runtime.get("config_json"), dict) else {}
    think_enabled = config_json.get("think")
    if think_enabled is None:
        think_enabled = bool(reasoning_effort)
    if runtime_driver == "ollama" and think_enabled:
        return max(1024, resolved_max_tokens)
    return resolved_max_tokens


def _runtime_supports_requested_tools(runtime: dict[str, Any], *, tools: list[dict] | None) -> bool:
    if not tools:
        return True
    if runtime.get("supports_tools") is False:
        return False
    runtime_driver = str(runtime.get("driver") or runtime.get("provider_name") or "").strip().lower()
    model_id = str(runtime.get("model") or runtime.get("model_id") or "").strip().lower()
    if runtime_driver == "ollama" and "gemma" in model_id:
        return False
    return True


def _provider_factory_kwargs(provider_factory, client_kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        signature = inspect.signature(provider_factory)
    except (TypeError, ValueError):
        return client_kwargs
    parameters = list(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters):
        return client_kwargs
    allowed_names = {
        param.name
        for param in parameters
        if param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {key: value for key, value in client_kwargs.items() if key in allowed_names}


def _resolve_retry_count(runtime: dict[str, Any], key: str, *, default: int = 1) -> int:
    raw_value = runtime.get(key)
    if raw_value is None:
        return max(0, int(default))
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return max(0, int(default))


def _context_pressure_retry_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    estimated = _estimate_message_tokens(messages)
    if estimated <= 1:
        return messages
    target_budget = max(512, math.floor(estimated * 0.7))
    trimmed = _trim_messages_to_budget(messages, target_budget)
    return trimmed if trimmed != messages else _trim_messages_to_budget(messages, max(256, estimated - 512))


def _messages_for_runtime(runtime: dict[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    driver = str(runtime.get("driver") or runtime.get("provider_name") or "").strip().lower()
    if driver == "bedrock":
        return messages
    return [{key: value for key, value in message.items() if key != "cache_scope"} for message in messages]


async def _chat_with_runtime_fallback(
    runtimes: list[dict],
    *,
    messages: list[dict],
    tools: list[dict] | None,
    max_tokens: int = 4096,
    reasoning_effort: str | None = None,
    request_timeout_seconds: float = 150.0,
    get_provider_func=None,
    retry_policy: RuntimeRetryPolicy | None = None,
    context_guard: Callable[[dict, list[dict]], None] | None = None,
) -> tuple[dict, dict, list[dict[str, Any]]]:
    class RuntimeFallbackError(RuntimeError):
        def __init__(self, message: str, attempts: list[dict[str, Any]]):
            super().__init__(message)
            self.runtime_attempts = attempts

    errors = []
    attempts: list[dict[str, Any]] = []
    provider_factory = get_provider_func or _default_get_provider
    normalized_retry_policy = dict(retry_policy or {})
    max_unreachable_retry_count = max(0, int(normalized_retry_policy.get("max_retries") or 0))
    if tools:
        # Tool-enabled turns are already expensive and user-visible. Repeating the entire
        # runtime chain after every provider has already timed out or gone unreachable
        # turns a single chat request into a multi-minute stall. Keep the synchronous
        # contract bounded to one full chain for tool-capable runs.
        max_unreachable_retry_count = 0
    unreachable_retry_pause_seconds = max(0.0, float(normalized_retry_policy.get("pause_seconds") or 0.0))
    fallback_mode = str(normalized_retry_policy.get("fallback_mode") or RUNTIME_FALLBACK_MODE_ALL_RUNTIMES)
    fallback_to_next_runtime_allowed = fallback_mode != RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY

    def _is_unreachable_retry_candidate(attempt: dict[str, Any]) -> bool:
        return attempt.get("status") == "error" and attempt.get("error_class") in {"timeout", "unreachable"}

    def _is_final_unreachable_candidate(attempt: dict[str, Any]) -> bool:
        return attempt.get("status") == "error" and attempt.get("error_class") == "unreachable"

    def _all_attempts_in_cycle_unreachable(cycle_attempts: list[dict[str, Any]]) -> bool:
        return bool(cycle_attempts) and all(_is_final_unreachable_candidate(attempt) for attempt in cycle_attempts)

    for retry_cycle_index in range(max_unreachable_retry_count + 1):
        cycle_errors: list[str] = []
        cycle_attempt_start_index = len(attempts)
        halt_error_class = ""
        for runtime_index, runtime in enumerate(runtimes):
            if not _runtime_supports_requested_tools(runtime, tools=tools):
                attempts.append(
                    {
                        "provider": runtime.get("provider_name"),
                        "model": runtime.get("model"),
                        "target_id": runtime.get("target_id"),
                        "priority": runtime.get("priority"),
                        "status": "skipped",
                        "error": "runtime does not support requested tool calls",
                        "retry_cycle_index": retry_cycle_index,
                    }
                )
                cycle_errors.append(
                    f"{runtime['provider_name']}:{runtime['model']}: runtime does not support requested tool calls"
                )
                continue
            admission_denial = runtime_admission_denial(runtime)
            if admission_denial is not None:
                record_admission_denial(
                    runtime,
                    admission_denial,
                    retry_cycle_index=retry_cycle_index,
                    attempts=attempts,
                    cycle_errors=cycle_errors,
                )
                continue
            runtime_client_kwargs = _runtime_client_kwargs_for_turn(runtime, reasoning_effort=reasoning_effort)
            attempt_messages = messages
            attempt_max_tokens = max_tokens
            transient_retries_remaining = _resolve_retry_count(runtime, "max_runtime_retries", default=1)
            context_retries_remaining = _resolve_retry_count(runtime, "max_context_retries", default=1)
            malformed_retries_remaining = _resolve_retry_count(runtime, "max_malformed_retries", default=1)
            has_additional_runtimes = fallback_to_next_runtime_allowed and runtime_index < len(runtimes) - 1
            retry_index = 0
            retry_history: list[dict[str, Any]] = []
            non_fallbackable_failure = False
            while True:
                if context_guard is not None:
                    try:
                        context_guard(runtime, attempt_messages)
                    except Exception as error:
                        error.runtime_attempts = list(attempts)
                        raise
                client = None
                started = time.perf_counter()
                try:
                    runtime_timeout_seconds = runtime.get("request_timeout_seconds")
                    try:
                        effective_timeout_seconds = float(runtime_timeout_seconds)
                    except (TypeError, ValueError):
                        effective_timeout_seconds = float(request_timeout_seconds)
                    if effective_timeout_seconds <= 0:
                        effective_timeout_seconds = float(request_timeout_seconds)
                    client = provider_factory(**_provider_factory_kwargs(provider_factory, runtime_client_kwargs))
                    chat_kwargs = {
                        "messages": _messages_for_runtime(runtime, attempt_messages),
                        "tools": tools,
                        "model": runtime["model"],
                        "max_tokens": _runtime_max_tokens_for_turn(
                            runtime,
                            max_tokens=attempt_max_tokens,
                            reasoning_effort=reasoning_effort,
                        ),
                    }
                    if reasoning_effort is not None:
                        chat_kwargs["reasoning_effort"] = reasoning_effort
                    response = await asyncio.wait_for(client.chat(**chat_kwargs), timeout=effective_timeout_seconds)
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    normalized_response = dict(response or {})
                    usage = (
                        dict(normalized_response.get("usage") or {})
                        if isinstance(normalized_response.get("usage"), dict)
                        else {}
                    )
                    usage.setdefault("request_duration_ms", duration_ms)
                    normalized_response["usage"] = usage
                    normalized_response["model"] = str(
                        normalized_response.get("model") or runtime.get("model") or ""
                    ).strip()
                    content = str(response.get("content") or "")
                    tool_calls = response.get("tool_calls") or []
                    if not content.strip() and not tool_calls:
                        if len(runtimes) == 1 and not str(runtime.get("target_id") or "").strip():
                            normalized_response["empty_assistant_output"] = True
                            attempts.append(
                                _build_runtime_attempt(
                                    runtime,
                                    status="success",
                                    duration_ms=duration_ms,
                                    retry_index=retry_index,
                                    retry_history=retry_history,
                                    empty_assistant_output=True,
                                    retry_cycle_index=retry_cycle_index,
                                )
                            )
                            attempts, _ = attach_runtime_recovery_telemetry(attempts)
                            return normalized_response, runtime, attempts
                        error_message = "empty assistant output without tool calls"
                        attempts.append(
                            _build_runtime_attempt(
                                runtime,
                                status="error",
                                duration_ms=duration_ms,
                                error=error_message,
                                error_class="empty_output",
                                attempt_stage="chat",
                                retry_decision="fallback_next_runtime",
                                retry_index=retry_index,
                                empty_assistant_output=True,
                                retry_cycle_index=retry_cycle_index,
                            )
                        )
                        cycle_errors.append(f"{runtime['provider_name']}:{runtime['model']}: {error_message}")
                        break
                    attempts.append(
                        _build_runtime_attempt(
                            runtime,
                            status="success",
                            duration_ms=duration_ms,
                            retry_index=retry_index,
                            retry_history=retry_history,
                            retry_cycle_index=retry_cycle_index,
                        )
                    )
                    attach_content_notice(attempts[-1], response)  # what a content policy changed
                    attempts, _ = attach_runtime_recovery_telemetry(attempts)
                    return normalized_response, runtime, attempts
                except TimeoutError:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    error_message = f"request timed out after {effective_timeout_seconds:.0f}s"
                    retry_plan = plan_timeout_retry(
                        has_additional_runtimes=has_additional_runtimes,
                        transient_retries_remaining=transient_retries_remaining,
                        retry_index=retry_index,
                    )
                    attempts.append(
                        _build_runtime_attempt(
                            runtime,
                            status="error",
                            duration_ms=duration_ms,
                            error=error_message,
                            error_class="timeout",
                            # Caught by exception type (``TimeoutError``), never by message.
                            error_class_source=CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
                            attempt_stage="chat",
                            retry_decision=retry_plan.retry_decision,
                            retry_index=retry_index,
                            retry_cycle_index=retry_cycle_index,
                        )
                    )
                    cycle_errors.append(f"{runtime['provider_name']}:{runtime['model']}: {error_message}")
                    if retry_plan.should_retry:
                        transient_retries_remaining -= 1
                        _record_retry_history(
                            retry_history,
                            retry_index=retry_index + 1,
                            error_class="timeout",
                            retry_decision=retry_plan.retry_decision,
                            error=error_message,
                        )
                        retry_index += 1
                        await asyncio.sleep(retry_plan.sleep_seconds)
                        continue
                    break
                except Exception as exc:
                    duration_ms = int((time.perf_counter() - started) * 1000)
                    error_message = str(exc)
                    classification = classify_runtime_error(exc, provider_init=client is None)
                    error_class = classification.error_class
                    non_fallbackable_failure = error_class in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES
                    retry_plan = plan_exception_retry(
                        error_class=error_class,
                        has_additional_runtimes=has_additional_runtimes,
                        transient_retries_remaining=transient_retries_remaining,
                        context_retries_remaining=context_retries_remaining,
                        malformed_retries_remaining=malformed_retries_remaining,
                        attempt_messages=attempt_messages,
                        attempt_max_tokens=attempt_max_tokens,
                        default_max_tokens=max_tokens,
                        retry_index=retry_index,
                        context_pressure_retry_messages=_context_pressure_retry_messages,
                    )
                    attempts.append(
                        _build_runtime_attempt(
                            runtime,
                            status="error",
                            duration_ms=duration_ms,
                            error=error_message,
                            error_class=error_class,
                            error_class_source=classification.source,
                            attempt_stage="provider_init" if client is None else "chat",
                            retry_decision=retry_plan.retry_decision,
                            retry_index=retry_index,
                            retry_cycle_index=retry_cycle_index,
                        )
                    )
                    # A provider's own sanitized cause (``ProviderRuntimeError.safe_detail``), never ``str(exc)``.
                    if isinstance(getattr(exc, "safe_detail", None), str) and exc.safe_detail:
                        attempts[-1]["safe_detail"] = exc.safe_detail[:400]
                    attach_content_notice(attempts[-1], exc)  # a content refusal's chat notice
                    cycle_errors.append(f"{runtime['provider_name']}:{runtime['model']}: {error_message}")
                    if retry_plan.should_retry:
                        if error_class == "context_pressure":
                            context_retries_remaining -= 1
                            attempt_messages = retry_plan.next_messages or attempt_messages
                            attempt_max_tokens = retry_plan.next_max_tokens or attempt_max_tokens
                        elif error_class == "malformed_response":
                            malformed_retries_remaining -= 1
                        elif error_class in {"transient", "timeout"}:
                            transient_retries_remaining -= 1
                        _record_retry_history(
                            retry_history,
                            retry_index=retry_index + 1,
                            error_class=error_class,
                            retry_decision=retry_plan.retry_decision,
                            error=error_message,
                        )
                        retry_index += 1
                        if retry_plan.sleep_seconds > 0:
                            await asyncio.sleep(retry_plan.sleep_seconds)
                        continue
                    break
                finally:
                    if client is not None:
                        try:
                            await client.close()
                        except Exception:
                            pass
            if non_fallbackable_failure:
                # A served response violated its pinned contract. Another
                # attempt would buy a second billable answer for a
                # deterministic defect, so the chain stops here.
                halt_error_class = CHAIN_HALT_ERROR_CLASS
                break
            if not fallback_to_next_runtime_allowed and runtime_index < len(runtimes) - 1:
                skipped_runtime_count = len(runtimes) - runtime_index - 1
                attempts.append(
                    {
                        "provider": "runtime-fallback",
                        "model": "fallback-policy",
                        "status": "fallback_denied",
                        "retry_cycle_index": retry_cycle_index,
                        "retry_decision": "final_error",
                        "error_class": "fallback_denied_by_policy",
                        "error": (
                            "Runtime fallback policy 'first_runtime_only' stopped this turn after the "
                            f"first runtime failed; {skipped_runtime_count} configured fallback runtime(s) were not tried."
                        ),
                    }
                )
                cycle_errors.append(
                    "runtime fallback to additional runtimes denied by policy (first_runtime_only)"
                )
                break
        if halt_error_class:
            record_chain_halt(
                runtime_count=len(runtimes),
                runtime_index=runtime_index,
                retry_cycle_index=retry_cycle_index,
                error_class=halt_error_class,
                attempts=attempts,
            )
            attempts, _ = attach_runtime_recovery_telemetry(attempts)
            raise RuntimeFallbackError("All configured runtime targets failed:\n" + "\n".join(cycle_errors), attempts)
        errors = cycle_errors
        cycle_attempts = attempts[cycle_attempt_start_index:]
        should_retry_all_runtimes = (
            retry_cycle_index < max_unreachable_retry_count and _all_attempts_in_cycle_unreachable(cycle_attempts)
        )
        if should_retry_all_runtimes:
            attempts.append(
                {
                    "provider": "runtime-fallback",
                    "model": "retry-loop",
                    "status": "retry_wait",
                    "retry_cycle_index": retry_cycle_index,
                    "retry_decision": "retry_all_runtimes",
                    "sleep_seconds": unreachable_retry_pause_seconds,
                    "error_class": "all_runtimes_unreachable",
                    "error": "all configured runtimes were unreachable or non-responsive in this retry cycle",
                }
            )
            if unreachable_retry_pause_seconds > 0:
                await asyncio.sleep(unreachable_retry_pause_seconds)
            continue
        break

    attempts, _ = attach_runtime_recovery_telemetry(attempts)
    final_cycle_attempts = [attempt for attempt in attempts if attempt.get("status") != "retry_wait"]
    if _all_attempts_in_cycle_unreachable(
        [attempt for attempt in final_cycle_attempts if attempt.get("retry_cycle_index") == retry_cycle_index]
    ):
        raise RuntimeFallbackError(
            "No runtime is currently reachable. All configured runtimes were unreachable or non-responsive.",
            attempts,
        )
    raise RuntimeFallbackError("All configured runtime targets failed:\n" + "\n".join(errors), attempts)


def _normalize_runtime_chat_result(
    result: tuple[Any, ...],
) -> tuple[AgentResponse, RuntimeTarget, list[dict[str, Any]]]:
    if len(result) >= 3:
        response, runtime, attempts = result[0], result[1], result[2]
        return response, runtime, list(attempts or [])
    if len(result) == 2:
        response, runtime = result
        return (
            response,
            runtime,
            [
                {
                    "provider": runtime.get("provider_name"),
                    "model": runtime.get("model"),
                    "target_id": runtime.get("target_id"),
                    "priority": runtime.get("priority"),
                    "status": "success",
                }
            ],
        )
    raise ValueError("Unexpected chat runtime result shape")
