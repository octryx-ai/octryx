"""Inputs of ``execute_runtime_turn`` and the response-guard inputs it builds from them."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..response._loop_response_guard_inputs import ResponseGuardInputs


@dataclass(kw_only=True)
class RuntimeTurnInputs:
    """The inputs of ``execute_runtime_turn``; unknown or missing names raise ``TypeError``."""

    db: Any
    session_id: str
    user_id: str
    current_runtimes: list[dict[str, Any]]
    request_messages: list[dict[str, Any]]
    current_tool_definitions: list[dict[str, Any]]
    provider_max_tokens: int | None
    provider_reasoning_effort: str | None
    request_timeout_seconds: float
    forced_tool_calls: list[dict[str, Any]] | None
    runtime_settings: dict[str, Any]
    tool_context: Any
    request_analysis: dict[str, Any]
    covered_evidence_axes: set[str]
    current_allowed_tool_names: set[str]
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_tool_activity: bool
    current_step_wrapup_forced: bool
    workflow_artifact_ready_for_final_response: bool = False
    active_steps: list[dict[str, Any]]
    current_turn_content: str
    capability_type: str
    context_plan: Any
    turn_tool_history: list[dict[str, Any]]
    step_tool_history: list[dict[str, Any]]
    executed_tool_names: set[str]
    tdd_cycle_state: dict[str, Any] | None
    total_tokens_in: int
    total_tokens_out: int
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    consecutive_coding_no_execution_count: int
    context_snapshot: dict[str, Any]
    messages: list[dict[str, Any]]
    chat_with_runtime_fallback: Callable[..., Any]
    normalize_runtime_chat_result: Callable[
        [tuple[Any, ...]],
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    ]
    dispatch_loop_runtime_response: Callable[..., Any]
    record_usage_event: Callable[..., Any]
    apply_workflow_response_override: Callable[..., Any]
    workflow_contract_from_request_analysis: Callable[[dict[str, Any]], dict[str, Any] | None]
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]]
    handle_response_guards: Callable[[ResponseGuardInputs], Awaitable[dict[str, Any]]]
    persist_traced_assistant_message: Callable[..., Any]
    persist_runtime_assistant_response: Callable[..., Any]
    event_factory: Callable[..., Any]
    is_transitional_assistant_response: Callable[..., bool]
    is_transitional_tool_call_preamble: Callable[..., bool]
    is_non_substantive_assistant_response: Callable[..., bool]
    looks_like_step_completion_summary: Callable[..., bool]
    allows_noop_step_completion: Callable[..., bool]
    build_required_tool_reminder: Callable[..., str]
    build_stalled_step_message: Callable[..., str]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_turn_trace: Callable[..., Any]
    build_tdd_cycle_incomplete_reminder: Callable[..., str]
    build_initial_tdd_cycle_state: Callable[[], dict[str, Any]]
    is_tdd_cycle_complete: Callable[..., bool]
    is_tdd_cycle_step: Callable[..., bool]
    _has_meaningful_coding_execution: Callable[..., bool]
    _is_probable_coding_change_request: Callable[..., bool]
    _looks_like_coding_intent_only_response: Callable[..., bool]
    _is_self_review_step: Callable[..., bool]
    _is_self_review_step_complete: Callable[..., bool]
    _build_incomplete_self_review_reminder: Callable[..., str]
    workflow_artifact_contract_satisfied: Callable[..., bool]
    _build_runtime_error_salvage_message: Callable[..., Any]

def guard_inputs_from(
    turn: RuntimeTurnInputs,
    *,
    runtime: dict[str, Any],
    response: dict[str, Any],
    context_snapshot: dict[str, Any],
    runtime_attempts: list[dict[str, Any]],
    usage_model: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None,
    workflow_contract: dict[str, Any] | None,
    total_tokens_in: int,
    total_tokens_out: int,
) -> ResponseGuardInputs:
    """The response-guard inputs: the turn's own inputs unchanged plus the state of the runtime response."""
    return ResponseGuardInputs(
        db=turn.db, session_id=turn.session_id, request_messages=turn.request_messages, messages=turn.messages,
        runtime_settings=turn.runtime_settings, current_tool_definitions=turn.current_tool_definitions,
        current_step=turn.current_step, current_step_index=turn.current_step_index,
        current_step_iterations=turn.current_step_iterations,
        current_step_max_iterations=turn.current_step_max_iterations,
        current_step_tool_activity=turn.current_step_tool_activity,
        current_step_wrapup_forced=turn.current_step_wrapup_forced, active_steps=turn.active_steps,
        current_turn_content=turn.current_turn_content, capability_type=turn.capability_type,
        tool_context=turn.tool_context, request_analysis=turn.request_analysis, context_plan=turn.context_plan,
        turn_tool_history=turn.turn_tool_history, step_tool_history=turn.step_tool_history,
        executed_tool_names=turn.executed_tool_names, covered_evidence_axes=turn.covered_evidence_axes,
        workflow_artifact_ready_for_final_response=turn.workflow_artifact_ready_for_final_response,
        tdd_cycle_state=turn.tdd_cycle_state,
        consecutive_non_progress_response_count=turn.consecutive_non_progress_response_count,
        consecutive_transitional_response_count=turn.consecutive_transitional_response_count,
        consecutive_coding_no_execution_count=turn.consecutive_coding_no_execution_count,
        is_transitional_assistant_response=turn.is_transitional_assistant_response,
        is_transitional_tool_call_preamble=turn.is_transitional_tool_call_preamble,
        is_non_substantive_assistant_response=turn.is_non_substantive_assistant_response,
        looks_like_step_completion_summary=turn.looks_like_step_completion_summary,
        allows_noop_step_completion=turn.allows_noop_step_completion,
        build_required_tool_reminder=turn.build_required_tool_reminder,
        build_stalled_step_message=turn.build_stalled_step_message,
        persist_suppressed_runtime_response=turn.persist_suppressed_runtime_response,
        persist_turn_trace=turn.persist_turn_trace,
        persist_traced_assistant_message=turn.persist_traced_assistant_message,
        build_tdd_cycle_incomplete_reminder=turn.build_tdd_cycle_incomplete_reminder,
        build_initial_tdd_cycle_state=turn.build_initial_tdd_cycle_state,
        is_tdd_cycle_complete=turn.is_tdd_cycle_complete, is_tdd_cycle_step=turn.is_tdd_cycle_step,
        _has_meaningful_coding_execution=turn._has_meaningful_coding_execution,
        _is_probable_coding_change_request=turn._is_probable_coding_change_request,
        _looks_like_coding_intent_only_response=turn._looks_like_coding_intent_only_response,
        _is_self_review_step=turn._is_self_review_step,
        _is_self_review_step_complete=turn._is_self_review_step_complete,
        _build_incomplete_self_review_reminder=turn._build_incomplete_self_review_reminder,
        workflow_artifact_contract_satisfied=turn.workflow_artifact_contract_satisfied,
        runtime=runtime, response=response, context_snapshot=context_snapshot, runtime_attempts=runtime_attempts,
        usage_model=usage_model, content=content, tool_calls=tool_calls, workflow_contract=workflow_contract,
        total_tokens_in=total_tokens_in, total_tokens_out=total_tokens_out,
    )


def input_values(inputs: Any, names: tuple[str, ...]) -> dict[str, Any]:
    """The named inputs as keyword arguments for a collaborator."""
    return {name: getattr(inputs, name) for name in names}

