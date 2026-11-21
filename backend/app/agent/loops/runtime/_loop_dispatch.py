"""Runtime dispatch helpers for the standard agent loop."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


async def dispatch_loop_runtime_response(
    *,
    current_runtimes: list[dict[str, Any]],
    request_messages: list[dict[str, Any]],
    current_tool_definitions: list[dict[str, Any]],
    provider_max_tokens: int | None,
    provider_reasoning_effort: str | None,
    request_timeout_seconds: float,
    chat_with_runtime_fallback: Callable[..., Any],
    normalize_runtime_chat_result: Callable[
        [tuple[Any, ...]], tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]
    ],
    forced_tool_calls: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]] | None]:
    if forced_tool_calls:
        runtime = {"provider_name": "workflow", "model": "deterministic-workflow"}
        response = {
            "content": "",
            "tool_calls": forced_tool_calls,
            "model": runtime["model"],
            "usage": {},
        }
        runtime_attempts = [
            {
                "provider": runtime["provider_name"],
                "model": runtime["model"],
                "status": "synthetic_workflow_dispatch",
            }
        ]
        return response, runtime, runtime_attempts, None

    chat_kwargs: dict[str, Any] = {
        "runtimes": current_runtimes,
        "messages": request_messages,
        "tools": current_tool_definitions if current_tool_definitions else None,
        "max_tokens": provider_max_tokens,
        "reasoning_effort": provider_reasoning_effort,
    }
    if "request_timeout_seconds" in inspect.signature(chat_with_runtime_fallback).parameters:
        chat_kwargs["request_timeout_seconds"] = request_timeout_seconds
    # The turn's runtime chain only: a runtime changes within a turn solely through
    # the provider fallback's explicit, logged failover, never a second hidden chain.
    response, runtime, runtime_attempts = normalize_runtime_chat_result(
        await chat_with_runtime_fallback(**chat_kwargs)
    )
    return response, runtime, runtime_attempts, forced_tool_calls
