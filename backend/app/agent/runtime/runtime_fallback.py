"""Runtime selection and fallback chat helpers for the engine."""

import asyncio
import inspect
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agent.providers import get_provider as _default_get_provider
from app.agent.runtime.attempt_admission import (
    CHAIN_HALT_ERROR_CLASS,
    record_admission_denial,
    record_chain_halt,
)
from app.agent.runtime.attempts import _build_runtime_attempt, _record_retry_history
from app.agent.runtime.message_helpers import _estimate_message_tokens, _trim_messages_to_budget
from app.agent.runtime.retry_policy import (
    RUNTIME_FALLBACK_MODE_ALL_RUNTIMES,
    RuntimeRetryPolicy,
    plan_exception_retry,
    plan_timeout_retry,
)
from app.agent.runtime.runtime_admission_contract import runtime_admission_denial
from app.agent.runtime.runtime_errors import (
    CLASSIFICATION_SOURCE_EXCEPTION_TYPE,
    NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES,
    classify_runtime_error,
)
from app.agent.runtime.runtime_fallback_policy import RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
from app.agent.runtime.runtime_recovery_telemetry import attach_runtime_recovery_telemetry
from app.services.content_routing.notices import attach_to_attempt as attach_content_notice

_NON_CLIENT_KEYS = frozenset({
    "provider_id",
    "target_id",
    "priority",
    "model",
    "supports_tools",
    "supports_vision",
    "max_tokens_per_request",
    "request_timeout_seconds",
})


def _runtime_client_kwargs_for_turn(runtime: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in runtime.items() if key not in _NON_CLIENT_KEYS}


def _runtime_supports_requested_tools(runtime: dict[str, Any], *, tools: list[dict] | None) -> bool:
    return not tools or runtime.get("supports_tools") is not False


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


def _messages_for_runtime(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in message.items() if key != "cache_scope"} for message in messages]


class RuntimeFallbackError(RuntimeError):
    def __init__(self, message: str, attempts: list[dict[str, Any]]):
        super().__init__(message)
        self.runtime_attempts = attempts


def _unreachable(attempt: dict[str, Any]) -> bool:
    return attempt.get("status") == "error" and attempt.get("error_class") == "unreachable"


def _all_unreachable(cycle_attempts: list[dict[str, Any]]) -> bool:
    return bool(cycle_attempts) and all(_unreachable(attempt) for attempt in cycle_attempts)


def _label(runtime: dict) -> str:
    return f"{runtime['provider_name']}:{runtime['model']}"


@dataclass
class _RuntimeTry:
    # One runtime's attempts within a cycle: what it sends next and the retries it has left.
    messages: list[dict]
    max_tokens: int
    transient: int
    context: int
    malformed: int
    index: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)
    non_fallbackable: bool = False


_RETRY, _STOP = "retry", "stop"


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
    chain = _FallbackChain(runtimes, messages=messages, tools=tools, max_tokens=max_tokens,
                           reasoning_effort=reasoning_effort, request_timeout_seconds=request_timeout_seconds,
                           provider_factory=get_provider_func or _default_get_provider,
                           retry_policy=dict(retry_policy or {}), context_guard=context_guard)
    return await chain.run()


class _FallbackChain:
    def __init__(self, runtimes: list[dict], *, messages: list[dict], tools: list[dict] | None, max_tokens: int,
                 reasoning_effort: str | None, request_timeout_seconds: float, provider_factory,
                 retry_policy: dict[str, Any], context_guard: Callable[[dict, list[dict]], None] | None) -> None:
        self.runtimes, self.messages, self.tools, self.max_tokens = runtimes, messages, tools, max_tokens
        self.reasoning_effort, self.request_timeout_seconds = reasoning_effort, request_timeout_seconds
        self.provider_factory, self.context_guard = provider_factory, context_guard
        # Tool-enabled turns are already expensive and user-visible. Repeating the entire runtime chain after every
        # provider has already timed out or gone unreachable turns a single chat request into a multi-minute stall.
        # Keep the synchronous contract bounded to one full chain for tool-capable runs.
        self.max_cycle_retries = 0 if tools else max(0, int(retry_policy.get("max_retries") or 0))
        self.unreachable_pause = max(0.0, float(retry_policy.get("pause_seconds") or 0.0))
        fallback_mode = str(retry_policy.get("fallback_mode") or RUNTIME_FALLBACK_MODE_ALL_RUNTIMES)
        self.fallback_allowed = fallback_mode != RUNTIME_FALLBACK_MODE_FIRST_RUNTIME_ONLY
        self.attempts: list[dict[str, Any]] = []
        self.cycle = 0
        self.cycle_errors: list[str] = []

    async def run(self) -> tuple[dict, dict, list[dict[str, Any]]]:
        errors: list[str] = []
        for cycle in range(self.max_cycle_retries + 1):
            self.cycle, self.cycle_errors = cycle, []
            cycle_start = len(self.attempts)
            result, halted, runtime_index = await self._run_cycle()
            if result is not None:
                return result
            if halted:
                record_chain_halt(runtime_count=len(self.runtimes), runtime_index=runtime_index,
                                  retry_cycle_index=cycle, error_class=CHAIN_HALT_ERROR_CLASS,
                                  attempts=self.attempts)
                self.attempts, _ = attach_runtime_recovery_telemetry(self.attempts)
                raise RuntimeFallbackError("All configured runtime targets failed:\n" + "\n".join(self.cycle_errors),
                                           self.attempts)
            errors = self.cycle_errors
            if cycle < self.max_cycle_retries and _all_unreachable(self.attempts[cycle_start:]):
                self.attempts.append({
                    "provider": "runtime-fallback",
                    "model": "retry-loop",
                    "status": "retry_wait",
                    "retry_cycle_index": cycle,
                    "retry_decision": "retry_all_runtimes",
                    "sleep_seconds": self.unreachable_pause,
                    "error_class": "all_runtimes_unreachable",
                    "error": "all configured runtimes were unreachable or non-responsive in this retry cycle",
                })
                if self.unreachable_pause > 0:
                    await asyncio.sleep(self.unreachable_pause)
                continue
            break
        self.attempts, _ = attach_runtime_recovery_telemetry(self.attempts)
        final_attempts = [attempt for attempt in self.attempts if attempt.get("status") != "retry_wait"]
        if _all_unreachable([attempt for attempt in final_attempts if attempt.get("retry_cycle_index") == self.cycle]):
            raise RuntimeFallbackError(
                "No runtime is currently reachable. All configured runtimes were unreachable or non-responsive.",
                self.attempts,
            )
        raise RuntimeFallbackError("All configured runtime targets failed:\n" + "\n".join(errors), self.attempts)

    async def _run_cycle(self) -> tuple[tuple | None, bool, int]:
        # (the response, the runtime and the attempts | None, whether the chain halts, the last runtime's index)
        runtime_index = 0
        for runtime_index, runtime in enumerate(self.runtimes):
            if not _runtime_supports_requested_tools(runtime, tools=self.tools):
                self._skip_without_tools(runtime)
                continue
            admission_denial = runtime_admission_denial(runtime)
            if admission_denial is not None:
                record_admission_denial(runtime, admission_denial, retry_cycle_index=self.cycle,
                                        attempts=self.attempts, cycle_errors=self.cycle_errors)
                continue
            result, non_fallbackable = await self._try_runtime(runtime, runtime_index)
            if result is not None:
                return result, False, runtime_index
            if non_fallbackable:
                # A served response violated its pinned contract. Another attempt would buy a second billable
                # answer for a deterministic defect, so the chain stops here.
                return None, True, runtime_index
            if not self.fallback_allowed and runtime_index < len(self.runtimes) - 1:
                self._deny_fallback(len(self.runtimes) - runtime_index - 1)
                break
        return None, False, runtime_index

    def _skip_without_tools(self, runtime: dict) -> None:
        self.attempts.append({
            "provider": runtime.get("provider_name"),
            "model": runtime.get("model"),
            "target_id": runtime.get("target_id"),
            "priority": runtime.get("priority"),
            "status": "skipped",
            "error": "runtime does not support requested tool calls",
            "retry_cycle_index": self.cycle,
        })
        self.cycle_errors.append(f"{_label(runtime)}: runtime does not support requested tool calls")

    def _deny_fallback(self, skipped_runtime_count: int) -> None:
        self.attempts.append({
            "provider": "runtime-fallback",
            "model": "fallback-policy",
            "status": "fallback_denied",
            "retry_cycle_index": self.cycle,
            "retry_decision": "final_error",
            "error_class": "fallback_denied_by_policy",
            "error": (
                "Runtime fallback policy 'first_runtime_only' stopped this turn after the "
                f"first runtime failed; {skipped_runtime_count} configured fallback runtime(s) were not tried."
            ),
        })
        self.cycle_errors.append("runtime fallback to additional runtimes denied by policy (first_runtime_only)")

    async def _try_runtime(self, runtime: dict, runtime_index: int) -> tuple[tuple | None, bool]:
        state = _RuntimeTry(messages=self.messages, max_tokens=self.max_tokens,
                            transient=_resolve_retry_count(runtime, "max_runtime_retries", default=1),
                            context=_resolve_retry_count(runtime, "max_context_retries", default=1),
                            malformed=_resolve_retry_count(runtime, "max_malformed_retries", default=1))
        has_additional = self.fallback_allowed and runtime_index < len(self.runtimes) - 1
        while True:
            if self.context_guard is not None:
                try:
                    self.context_guard(runtime, state.messages)
                except Exception as error:
                    error.runtime_attempts = list(self.attempts)
                    raise
            outcome = await self._call(runtime, state, has_additional)
            if outcome == _RETRY:
                continue
            if outcome == _STOP:
                return None, state.non_fallbackable
            return outcome, False

    def _timeout_seconds(self, runtime: dict) -> float:
        try:
            seconds = float(runtime.get("request_timeout_seconds"))
        except (TypeError, ValueError):
            seconds = float(self.request_timeout_seconds)
        return seconds if seconds > 0 else float(self.request_timeout_seconds)

    async def _call(self, runtime: dict, state: _RuntimeTry, has_additional: bool):
        # The response, the runtime and the attempts on success; else _RETRY or _STOP.
        client = None
        started = time.perf_counter()
        timeout_seconds = self._timeout_seconds(runtime)
        try:
            client = self.provider_factory(**_provider_factory_kwargs(self.provider_factory,
                                                                      _runtime_client_kwargs_for_turn(runtime)))
            chat_kwargs = {
                "messages": _messages_for_runtime(state.messages),
                "tools": self.tools,
                "model": runtime["model"],
                "max_tokens": int(runtime.get("max_tokens_per_request") or state.max_tokens),
            }
            if self.reasoning_effort is not None:
                chat_kwargs["reasoning_effort"] = self.reasoning_effort
            response = await asyncio.wait_for(client.chat(**chat_kwargs), timeout=timeout_seconds)
            return self._answered(runtime, state, response, int((time.perf_counter() - started) * 1000))
        except TimeoutError:
            return await self._timed_out(runtime, state, has_additional, started, timeout_seconds)
        except Exception as exc:
            return await self._failed(runtime, state, has_additional, started, exc, client)
        finally:
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

    def _answered(self, runtime: dict, state: _RuntimeTry, response: dict, duration_ms: int):
        normalized_response = dict(response or {})
        usage = dict(normalized_response.get("usage") or {}) if isinstance(normalized_response.get("usage"), dict) \
            else {}
        usage.setdefault("request_duration_ms", duration_ms)
        normalized_response["usage"] = usage
        normalized_response["model"] = str(normalized_response.get("model") or runtime.get("model") or "").strip()
        content = str(response.get("content") or "")
        if not content.strip() and not (response.get("tool_calls") or []):
            if len(self.runtimes) == 1 and not str(runtime.get("target_id") or "").strip():
                normalized_response["empty_assistant_output"] = True
                self.attempts.append(_build_runtime_attempt(
                    runtime, status="success", duration_ms=duration_ms, retry_index=state.index,
                    retry_history=state.history, empty_assistant_output=True, retry_cycle_index=self.cycle))
                self.attempts, _ = attach_runtime_recovery_telemetry(self.attempts)
                return normalized_response, runtime, self.attempts
            error_message = "empty assistant output without tool calls"
            self.attempts.append(_build_runtime_attempt(
                runtime, status="error", duration_ms=duration_ms, error=error_message, error_class="empty_output",
                attempt_stage="chat", retry_decision="fallback_next_runtime", retry_index=state.index,
                empty_assistant_output=True, retry_cycle_index=self.cycle))
            self.cycle_errors.append(f"{_label(runtime)}: {error_message}")
            return _STOP
        self.attempts.append(_build_runtime_attempt(
            runtime, status="success", duration_ms=duration_ms, retry_index=state.index,
            retry_history=state.history, retry_cycle_index=self.cycle))
        attach_content_notice(self.attempts[-1], response)  # what a content policy changed
        self.attempts, _ = attach_runtime_recovery_telemetry(self.attempts)
        return normalized_response, runtime, self.attempts

    async def _timed_out(self, runtime: dict, state: _RuntimeTry, has_additional: bool, started: float,
                         timeout_seconds: float) -> str:
        error_message = f"request timed out after {timeout_seconds:.0f}s"
        retry_plan = plan_timeout_retry(has_additional_runtimes=has_additional,
                                        transient_retries_remaining=state.transient, retry_index=state.index)
        self.attempts.append(_build_runtime_attempt(
            runtime, status="error", duration_ms=int((time.perf_counter() - started) * 1000), error=error_message,
            error_class="timeout",
            # Caught by exception type (``TimeoutError``), never by message.
            error_class_source=CLASSIFICATION_SOURCE_EXCEPTION_TYPE, attempt_stage="chat",
            retry_decision=retry_plan.retry_decision, retry_index=state.index, retry_cycle_index=self.cycle))
        self.cycle_errors.append(f"{_label(runtime)}: {error_message}")
        if not retry_plan.should_retry:
            return _STOP
        state.transient -= 1
        _record_retry_history(state.history, retry_index=state.index + 1, error_class="timeout",
                              retry_decision=retry_plan.retry_decision, error=error_message)
        state.index += 1
        await asyncio.sleep(retry_plan.sleep_seconds)
        return _RETRY

    async def _failed(self, runtime: dict, state: _RuntimeTry, has_additional: bool, started: float,
                      exc: Exception, client) -> str:
        error_message = str(exc)
        classification = classify_runtime_error(exc, provider_init=client is None)
        error_class = classification.error_class
        state.non_fallbackable = error_class in NON_FALLBACKABLE_RUNTIME_ERROR_CLASSES
        retry_plan = plan_exception_retry(
            error_class=error_class, has_additional_runtimes=has_additional,
            transient_retries_remaining=state.transient, context_retries_remaining=state.context,
            malformed_retries_remaining=state.malformed, attempt_messages=state.messages,
            attempt_max_tokens=state.max_tokens, default_max_tokens=self.max_tokens, retry_index=state.index,
            context_pressure_retry_messages=_context_pressure_retry_messages)
        self.attempts.append(_build_runtime_attempt(
            runtime, status="error", duration_ms=int((time.perf_counter() - started) * 1000), error=error_message,
            error_class=error_class, error_class_source=classification.source,
            attempt_stage="provider_init" if client is None else "chat", retry_decision=retry_plan.retry_decision,
            retry_index=state.index, retry_cycle_index=self.cycle))
        # A provider's own sanitized cause (``ProviderRuntimeError.safe_detail``), never ``str(exc)``.
        if isinstance(getattr(exc, "safe_detail", None), str) and exc.safe_detail:
            self.attempts[-1]["safe_detail"] = exc.safe_detail[:400]
        attach_content_notice(self.attempts[-1], exc)  # a content refusal's chat notice
        self.cycle_errors.append(f"{_label(runtime)}: {error_message}")
        if not retry_plan.should_retry:
            return _STOP
        if error_class == "context_pressure":
            state.context -= 1
            state.messages = retry_plan.next_messages or state.messages
            state.max_tokens = retry_plan.next_max_tokens or state.max_tokens
        elif error_class == "malformed_response":
            state.malformed -= 1
        elif error_class in {"transient", "timeout"}:
            state.transient -= 1
        _record_retry_history(state.history, retry_index=state.index + 1, error_class=error_class,
                              retry_decision=retry_plan.retry_decision, error=error_message)
        state.index += 1
        if retry_plan.sleep_seconds > 0:
            await asyncio.sleep(retry_plan.sleep_seconds)
        return _RETRY
