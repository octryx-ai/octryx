"""Trace-only LLM planner call helpers."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from app.services.prompt_catalog import render_prompt

from ....services.system_config.constants import (
    DEFAULT_LLM_TOOL_PLANNER_MAX_TOKENS,
    DEFAULT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS,
)
from ....services.tool_planning import parse_model_tool_plan_contract
from ...core.runtime.trace_runtime import compact_trace_value
from ...core.turn.decision_timeline import append_tool_planner_call_event

PLANNER_ENABLED_SETTING = "llm_tool_planner_trace_call_enabled"
PLANNER_MAX_TOKENS_SETTING = "llm_tool_planner_max_tokens"
PLANNER_TIMEOUT_SETTING = "llm_tool_planner_timeout_seconds"
DEFAULT_PLANNER_MAX_TOKENS = DEFAULT_LLM_TOOL_PLANNER_MAX_TOKENS
DEFAULT_PLANNER_TIMEOUT_SECONDS = float(DEFAULT_LLM_TOOL_PLANNER_TIMEOUT_SECONDS)


def _planner_enabled(runtime_settings: dict[str, Any]) -> bool:
    raw_value = runtime_settings.get(PLANNER_ENABLED_SETTING)
    if isinstance(raw_value, bool):
        return raw_value
    return str(raw_value or "").strip().lower() in {"1", "true", "yes", "on"}


def _planner_messages(prompt_packet: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": render_prompt("judge.planner.system"),
        },
        {
            "role": "user",
            "content": json.dumps(prompt_packet, ensure_ascii=False, sort_keys=True),
        },
    ]


def _planner_timeout(runtime_settings: dict[str, Any], request_timeout_seconds: float) -> float:
    raw_timeout = runtime_settings.get(PLANNER_TIMEOUT_SETTING)
    try:
        configured = float(raw_timeout)
    except (TypeError, ValueError):
        configured = DEFAULT_PLANNER_TIMEOUT_SECONDS
    if configured <= 0:
        configured = DEFAULT_PLANNER_TIMEOUT_SECONDS
    return max(1.0, min(configured, float(request_timeout_seconds or configured)))


def _record_planner_result(
    context_snapshot: dict[str, Any], result: dict[str, Any], *, trace_value: Any
) -> dict[str, Any]:
    context_snapshot["llm_tool_plan_model_response"] = trace_value
    append_tool_planner_call_event(context_snapshot, planner_result=result)
    return result


def _skipped_result(context_snapshot: dict[str, Any], skip_reason: str) -> dict[str, Any]:
    result = {
        "call_status": "skipped",
        "skip_reason": skip_reason,
        "validation": {"valid": False, "errors": [skip_reason], "warnings": []},
    }
    return _record_planner_result(context_snapshot, result, trace_value=result)


def _planner_chat_kwargs(
    *,
    prompt_packet: dict[str, Any],
    runtime_settings: dict[str, Any],
    current_runtimes: list[dict[str, Any]],
    provider_reasoning_effort: str | None,
    request_timeout_seconds: float,
    chat_with_runtime_fallback: Callable[..., Any],
) -> dict[str, Any]:
    chat_kwargs: dict[str, Any] = {
        "runtimes": current_runtimes,
        "messages": _planner_messages(prompt_packet),
        "tools": None,
        "max_tokens": int(runtime_settings.get(PLANNER_MAX_TOKENS_SETTING) or DEFAULT_PLANNER_MAX_TOKENS),
        "reasoning_effort": provider_reasoning_effort,
    }
    if "request_timeout_seconds" in inspect.signature(chat_with_runtime_fallback).parameters:
        chat_kwargs["request_timeout_seconds"] = _planner_timeout(runtime_settings, request_timeout_seconds)
    return chat_kwargs


def _completed_result(
    *,
    response: dict[str, Any],
    runtime: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    catalog: Any,
) -> dict[str, Any]:
    parsed_plan = parse_model_tool_plan_contract(
        str(response.get("content") or ""),
        session_tool_catalog=catalog if isinstance(catalog, dict) else None,
    )
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    return {
        "call_status": "completed",
        "provider": runtime.get("provider_name"),
        "model": response.get("model") or runtime.get("model"),
        "runtime_attempts": runtime_attempts,
        "usage": usage,
        "plan": parsed_plan,
        "validation": parsed_plan.get("validation"),
    }


def _failed_result(exc: Exception) -> dict[str, Any]:
    runtime_attempts = list(getattr(exc, "runtime_attempts", []) or [])
    return {
        "call_status": "failed",
        "error": str(exc),
        "runtime_attempts": runtime_attempts,
        "validation": {"valid": False, "errors": ["planner_call_failed"], "warnings": []},
    }


async def maybe_call_trace_only_tool_planner(
    *,
    context_snapshot: dict[str, Any],
    runtime_settings: dict[str, Any],
    current_runtimes: list[dict[str, Any]],
    provider_reasoning_effort: str | None,
    request_timeout_seconds: float,
    chat_with_runtime_fallback: Callable[..., Any],
    normalize_runtime_chat_result: Callable[
        [tuple[Any, ...]],
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    ],
    record_usage_event: Callable[..., Any],
    db,
    session_id: str,
    user_id: str,
    request_id: str,
) -> dict[str, Any] | None:
    """Optionally call the model planner and keep the result trace-only."""

    if not _planner_enabled(runtime_settings):
        return None
    prompt_packet = context_snapshot.get("llm_tool_plan_prompt_packet")
    catalog = context_snapshot.get("session_tool_catalog")
    if not isinstance(prompt_packet, dict):
        return _skipped_result(context_snapshot, "missing_prompt_packet")
    if not current_runtimes:
        return _skipped_result(context_snapshot, "no_runtime_available")

    try:
        chat_kwargs = _planner_chat_kwargs(
            prompt_packet=prompt_packet, runtime_settings=runtime_settings, current_runtimes=current_runtimes,
            provider_reasoning_effort=provider_reasoning_effort, request_timeout_seconds=request_timeout_seconds,
            chat_with_runtime_fallback=chat_with_runtime_fallback,
        )
        chat_result = await chat_with_runtime_fallback(**chat_kwargs)
        response, runtime, runtime_attempts = normalize_runtime_chat_result(chat_result)
        result = _completed_result(
            response=response, runtime=runtime, runtime_attempts=runtime_attempts, catalog=catalog
        )
        _record_planner_result(
            context_snapshot, result, trace_value=compact_trace_value(result, trace_limits=runtime_settings)
        )
        await record_usage_event(
            db=db,
            session_id=session_id,
            user_id=user_id,
            provider=str(runtime.get("provider_name") or "planner"),
            driver=str(runtime.get("driver") or ""),
            model=str(response.get("model") or runtime.get("model") or "unknown"),
            usage={**result["usage"], "planner_call": True},
            request_id=request_id,
        )
        return result
    except Exception as exc:
        result = _failed_result(exc)
        return _record_planner_result(
            context_snapshot, result, trace_value=compact_trace_value(result, trace_limits=runtime_settings)
        )


__all__ = [
    "PLANNER_ENABLED_SETTING",
    "maybe_call_trace_only_tool_planner",
]
