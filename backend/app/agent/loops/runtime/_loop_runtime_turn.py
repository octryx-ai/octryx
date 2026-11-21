"""Runtime turn execution for the standard agent loop."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.services.error_facts import error_text
from app.services.prompt_catalog import PROMPT_TEMPLATES_TRACE_KEY, bound_prompt_trace_record
from app.services.prompt_catalog.tool_descriptions import catalog_tool_descriptions

from ...core.runtime.trace_runtime import compact_trace_value
from ...core.turn.decision_timeline import append_quality_event, append_runtime_response_event
from ...engine.runtime._engine_runtime_retry_policy import RuntimeRetryPolicy, build_runtime_retry_policy
from ..control._loop_tool_planner import maybe_call_trace_only_tool_planner
from ._loop_runtime_response_repair import TurnResponse, enforce_evidence_backed_output, repair_runtime_response
from ._loop_runtime_turn_failure import (
    apply_runtime_recovery_telemetry,
    finish_runtime_failure,
    hold_research_context_failure,
    is_research_context_error,
)
from ._loop_runtime_turn_inputs import RuntimeTurnInputs, guard_inputs_from

__all__ = ["execute_runtime_turn"]

logger = logging.getLogger(__name__)


def _chat_with_retry_policy(inputs: RuntimeTurnInputs) -> Callable[..., Any]:
    """The runtime fallback chat bound to the turn's retry policy."""
    # The resolved chain decides the fallback default: a governed model
    # gateway target must not silently degrade to another runtime.
    retry_policy: RuntimeRetryPolicy = build_runtime_retry_policy(
        inputs.runtime_settings,
        runtimes=inputs.current_runtimes,
    )
    chat_with_runtime_fallback = inputs.chat_with_runtime_fallback

    async def _chat_with_runtime_retry_policy(
        *,
        runtimes,
        messages,
        tools,
        max_tokens=None,
        reasoning_effort=None,
        request_timeout_seconds=150.0,
        **kwargs,
    ) -> Any:
        return await chat_with_runtime_fallback(
            runtimes=runtimes,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            request_timeout_seconds=request_timeout_seconds,
            retry_policy=retry_policy,
            **kwargs,
        )

    return _chat_with_runtime_retry_policy


async def _dispatch_runtime(inputs: RuntimeTurnInputs) -> tuple[Any, Any, Any, Any]:
    """Trace-only planner, then the main dispatch; returns (response, runtime, runtime_attempts, forced_tool_calls)."""
    _chat_with_runtime_retry_policy = _chat_with_retry_policy(inputs)
    await maybe_call_trace_only_tool_planner(
        context_snapshot=inputs.context_snapshot,
        runtime_settings=inputs.runtime_settings,
        current_runtimes=inputs.current_runtimes,
        provider_reasoning_effort=inputs.provider_reasoning_effort,
        request_timeout_seconds=inputs.request_timeout_seconds,
        chat_with_runtime_fallback=_chat_with_runtime_retry_policy,
        normalize_runtime_chat_result=inputs.normalize_runtime_chat_result,
        record_usage_event=inputs.record_usage_event,
        db=inputs.db,
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        request_id=inputs.tool_context.request_id,
    )
    dispatched_forced_tool_calls = inputs.forced_tool_calls
    # The offered schemas with the turn's tool descriptions (prompt catalog); the trace's prompt
    # record is refreshed so it names the catalog versions this request carries.
    offered_tool_definitions = catalog_tool_descriptions(inputs.current_tool_definitions)
    inputs.context_snapshot[PROMPT_TEMPLATES_TRACE_KEY] = bound_prompt_trace_record()
    response, runtime, runtime_attempts, forced_tool_calls = await inputs.dispatch_loop_runtime_response(
        current_runtimes=inputs.current_runtimes,
        request_messages=inputs.request_messages,
        current_tool_definitions=offered_tool_definitions,
        provider_max_tokens=inputs.provider_max_tokens,
        provider_reasoning_effort=inputs.provider_reasoning_effort,
        request_timeout_seconds=inputs.request_timeout_seconds,
        chat_with_runtime_fallback=_chat_with_runtime_retry_policy,
        normalize_runtime_chat_result=inputs.normalize_runtime_chat_result,
        forced_tool_calls=inputs.forced_tool_calls,
    )
    if dispatched_forced_tool_calls:
        forced_tool_calls = None
    return response, runtime, runtime_attempts, forced_tool_calls


async def _record_runtime_usage(
    inputs: RuntimeTurnInputs, response: dict[str, Any], runtime: dict[str, Any], runtime_attempts: list[Any]
) -> tuple[int, int, str]:
    """Trace recovery and attempts, account the tokens and record the usage; returns (tokens_in, tokens_out, model)."""
    apply_runtime_recovery_telemetry(inputs, runtime_attempts)
    if runtime_attempts:
        inputs.context_snapshot["runtime_attempts"] = compact_trace_value(
            runtime_attempts, trace_limits=inputs.runtime_settings
        )
    total_tokens_in = inputs.total_tokens_in + response.get("usage", {}).get("prompt_tokens", 0)
    total_tokens_out = inputs.total_tokens_out + response.get("usage", {}).get("completion_tokens", 0)
    usage_model = str(response.get("model") or runtime["model"])
    await inputs.record_usage_event(
        db=inputs.db,
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        provider=runtime["provider_name"],
        # The driver key of the runtime that actually served this turn after any
        # fallback. Accounting trusts a declared cost source only from the
        # governed gateway driver.
        driver=runtime.get("driver"),
        model=usage_model,
        usage=response.get("usage", {}),
        request_id=inputs.tool_context.request_id,
    )
    return total_tokens_in, total_tokens_out, usage_model


def _guard_redirect_result(
    guard_outcome: dict[str, Any], turn: TurnResponse, turn_state: dict[str, Any], forced_tool_calls: Any
) -> dict[str, Any]:
    append_quality_event(
        turn.context_snapshot,
        title="Response guard redirected turn",
        status="info",
        detail=f"Guard action: {guard_outcome.get('action')}.",
        metadata={
            "action": guard_outcome.get("action"),
            "yield_model": guard_outcome.get("yield_model"),
        },
    )
    return {
        **guard_outcome,
        "runtime": turn_state["runtime"],
        "response": turn.response,
        "content": turn.content,
        "tool_calls": turn.tool_calls,
        "workflow_contract": turn.workflow_contract,
        "runtime_attempts": turn_state["runtime_attempts"],
        "total_tokens_in": turn_state["total_tokens_in"],
        "total_tokens_out": turn_state["total_tokens_out"],
        "usage_model": turn_state["usage_model"],
        "forced_tool_calls": guard_outcome.get("forced_tool_calls", forced_tool_calls),
        "context_snapshot": turn.context_snapshot,
    }


def _guard_counter_updates(inputs: RuntimeTurnInputs, guard_outcome: dict[str, Any]) -> dict[str, Any]:
    """Step and counter state the guards may have changed, falling back to the turn's inputs."""
    names = (
        "current_step_index", "current_step_iterations", "current_step_tool_activity", "current_step_wrapup_forced",
        "consecutive_non_progress_response_count", "consecutive_transitional_response_count",
        "consecutive_coding_no_execution_count",
    )
    return {name: guard_outcome.get(name, getattr(inputs, name)) for name in names}


async def _accept_runtime_turn(
    inputs: RuntimeTurnInputs,
    guard_outcome: dict[str, Any],
    turn: TurnResponse,
    turn_state: dict[str, Any],
    forced_tool_calls: Any,
) -> dict[str, Any]:
    # The answer evidence guard may deliver the reply with its uncited claims marked.
    turn.content = guard_outcome.get("content", turn.content)
    persisted_assistant_content = guard_outcome.get("persisted_assistant_content", turn.content)
    tool_calls = turn.tool_calls
    append_quality_event(
        turn.context_snapshot,
        title="Runtime turn accepted",
        status="info" if tool_calls else "ok",
        detail=(
            "Tool calls were queued for execution."
            if tool_calls
            else "No response guard blocked the final assistant response."
        ),
        metadata={"tool_call_count": len(tool_calls or [])},
    )
    assistant_msg, turn_trace = await inputs.persist_runtime_assistant_response(
        db=inputs.db,
        session_id=inputs.session_id,
        provider=turn_state["runtime"]["provider_name"],
        model=turn_state["usage_model"],
        request_messages=inputs.request_messages,
        context_snapshot=turn.context_snapshot,
        response=turn.response,
        runtime_attempts=turn_state["runtime_attempts"],
        content=persisted_assistant_content,
        tool_calls=tool_calls,
        trace_limits=inputs.runtime_settings,
    )
    return {
        "action": "ok",
        "assistant_msg": assistant_msg,
        "content": turn.content,
        "context_snapshot": turn.context_snapshot,
        **_guard_counter_updates(inputs, guard_outcome),
        "forced_tool_calls": forced_tool_calls,
        "persisted_assistant_content": persisted_assistant_content,
        "response": turn.response,
        "runtime": turn_state["runtime"],
        "runtime_attempts": turn_state["runtime_attempts"],
        "tool_calls": tool_calls,
        "total_tokens_in": turn_state["total_tokens_in"],
        "total_tokens_out": turn_state["total_tokens_out"],
        "turn_trace": turn_trace,
        "usage_model": turn_state["usage_model"],
        "workflow_contract": turn.workflow_contract,
    }


async def _run_response_guards(
    inputs: RuntimeTurnInputs, turn: TurnResponse, turn_state: dict[str, Any]
) -> dict[str, Any]:
    guard_outcome = await inputs.handle_response_guards(guard_inputs_from(
        inputs,
        runtime=turn_state["runtime"],
        response=turn.response,
        context_snapshot=turn.context_snapshot,
        runtime_attempts=turn_state["runtime_attempts"],
        usage_model=turn_state["usage_model"],
        content=turn.content,
        tool_calls=turn.tool_calls,
        workflow_contract=turn.workflow_contract,
        total_tokens_in=turn_state["total_tokens_in"],
        total_tokens_out=turn_state["total_tokens_out"],
    ))
    if guard_outcome.get("yield_content"):
        guard_outcome["event"] = inputs.event_factory(
            role="assistant",
            content=guard_outcome["yield_content"],
            model=guard_outcome.get("yield_model", turn_state["usage_model"]),
            tokens_in=turn_state["total_tokens_in"],
            tokens_out=turn_state["total_tokens_out"],
        )
    return guard_outcome


async def execute_runtime_turn(inputs: RuntimeTurnInputs) -> dict[str, Any]:
    try:
        response, runtime, runtime_attempts, forced_tool_calls = await _dispatch_runtime(inputs)
    except Exception as exc:
        if is_research_context_error(exc):
            return await hold_research_context_failure(inputs, exc)
        runtime_attempts = list(getattr(exc, "runtime_attempts", []) or [])
        # This failure ends the turn (possibly salvaged from this turn's own
        # evidence); it must be visible to operators, not only buried in the trace.
        logger.warning(
            "loop.runtime_call_failed session=%s error=%s error_classes=%s",
            inputs.session_id,
            error_text("runtime_call_failed", exc),
            sorted({str(attempt.get("error_class")) for attempt in runtime_attempts if attempt.get("error_class")}),
        )
        return await finish_runtime_failure(inputs, exc, runtime_attempts)

    total_tokens_in, total_tokens_out, usage_model = await _record_runtime_usage(
        inputs, response, runtime, runtime_attempts
    )
    turn_state = {
        "runtime": runtime,
        "runtime_attempts": runtime_attempts,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "usage_model": usage_model,
    }
    turn = TurnResponse(
        response=response,
        content=response.get("content", ""),
        tool_calls=response.get("tool_calls"),
        context_snapshot=inputs.context_snapshot,
    )
    repair_runtime_response(inputs, turn)
    enforce_evidence_backed_output(inputs, turn)
    append_runtime_response_event(
        turn.context_snapshot,
        runtime=runtime,
        model=usage_model,
        tool_calls=turn.tool_calls,
        content=turn.content,
    )
    guard_outcome = await _run_response_guards(inputs, turn, turn_state)
    if guard_outcome.get("action") in {"advance_step", "continue", "return"}:
        return _guard_redirect_result(guard_outcome, turn, turn_state, forced_tool_calls)
    return await _accept_runtime_turn(inputs, guard_outcome, turn, turn_state, forced_tool_calls)
