"""Inputs of ``run_runtime_cycle`` (request preparation reads them too) and the runtime-turn inputs."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..response._loop_response_guard_inputs import ResponseGuardInputs
from ._loop_runtime_turn_inputs import RuntimeTurnInputs


@dataclass(kw_only=True)
class RuntimeCycleInputs:
    """The inputs of ``run_runtime_cycle``; unknown or missing names raise ``TypeError``."""

    iteration: int
    runtimes: dict[str, Any]
    runtime_target_id: str | None
    tool_definitions: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    summary_context_msgs: list[dict[str, Any]]
    history: list[dict[str, Any]]
    thinking_level: str | None
    system_prompt: str
    personality_prompt: str
    memory_prompt: str
    skills_prompt: str
    system_context: str
    agent_definition: dict[str, Any] | None
    context_plan: dict[str, Any] | None
    request_analysis: dict[str, Any] | None
    tool_context: dict[str, Any]
    runtime_settings: dict[str, Any] | None
    capability_type: str
    current_turn_content: str
    active_steps: list[dict[str, Any]]
    current_step: dict[str, Any] | None
    current_step_for_runtime: dict[str, Any] | None
    current_step_index: int
    step_tool_history: list[dict[str, Any]]
    elastic_iteration: dict[str, Any]
    tdd_cycle_state: dict[str, Any] | None
    existing_thread_context: dict[str, Any] | None
    turn_diff_tracker: Any
    turn_tool_history: list[dict[str, Any]]
    covered_evidence_axes: set[str]
    workflow_artifact_ready_for_final_response: bool
    workflow_final_answer_prompted: bool
    workflow_contract: dict[str, Any] | None
    forced_tool_calls: list[dict[str, Any]] | None
    provider_max_tokens: int | None
    provider_reasoning_effort: str | None
    request_timeout_seconds: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_tool_activity: bool
    current_step_wrapup_forced: bool
    executed_tool_names: set[str]
    total_tokens_in: int
    total_tokens_out: int
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    consecutive_coding_no_execution_count: int
    prepare_runtime_request: Callable[[RuntimeCycleInputs], dict[str, Any]]
    execute_runtime_turn: Callable[[RuntimeTurnInputs], Awaitable[dict[str, Any]]]
    apply_runtime_turn_result: Callable[..., dict[str, Any]]
    build_current_step_prompt: Callable[[dict, int, int, str | None], str]
    filter_tool_definitions: Callable[[list[dict], list[str] | None], list[dict]]
    build_turn_working_summary_message: Callable[..., str | None]
    build_within_turn_working_set_messages: Callable[..., list[str]]
    plan_forced_tool_calls_for_turn: Callable[..., Any]
    _augment_step_allowed_tools_for_request_analysis: Callable[..., Any]
    _build_workflow_artifact_ready_message: Callable[..., str]
    _model_role_for_current_subtask: Callable[..., str | None]
    _latest_successful_tool_result_from_history: Callable[..., dict[str, Any] | None]
    _plan_coding_preflight_tool_calls: Callable[..., list[dict[str, Any]]]
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]]
    db: Any
    session_id: str
    user_id: str
    chat_with_runtime_fallback: Callable[..., Any]
    normalize_runtime_chat_result: Callable[
        [tuple[Any, ...]],
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    ]
    dispatch_loop_runtime_response: Callable[..., dict[str, Any]]
    record_usage_event: Callable[..., Any]
    apply_workflow_response_override: Callable[..., tuple[str, list[dict[str, Any]], bool]]
    workflow_contract_from_request_analysis: Callable[..., dict[str, Any] | None]
    handle_response_guards: Callable[[ResponseGuardInputs], Awaitable[dict[str, Any]]]
    persist_traced_assistant_message: Callable[..., Any]
    persist_runtime_assistant_response: Callable[..., Any]
    event_factory: Callable[..., Any]
    is_transitional_assistant_response: Callable[[str, list[dict[str, Any]] | None, bool], bool]
    is_transitional_tool_call_preamble: Callable[[str, list[dict[str, Any]] | None], bool]
    is_non_substantive_assistant_response: Callable[[str, list[dict[str, Any]] | None], bool]
    looks_like_step_completion_summary: Callable[[str], bool]
    allows_noop_step_completion: Callable[[dict[str, Any] | None, str], bool]
    build_required_tool_reminder: Callable[[dict[str, Any]], str]
    build_stalled_step_message: Callable[[dict[str, Any]], str]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_turn_trace: Callable[..., Any]
    build_tdd_cycle_incomplete_reminder: Callable[[dict[str, Any]], str]
    build_initial_tdd_cycle_state: Callable[[dict[str, Any] | None], dict[str, Any]]
    is_tdd_cycle_complete: Callable[[dict[str, Any] | None], bool]
    is_tdd_cycle_step: Callable[[dict[str, Any] | None], bool]
    _has_meaningful_coding_execution: Callable[..., bool]
    _is_probable_coding_change_request: Callable[..., bool]
    _looks_like_coding_intent_only_response: Callable[..., bool]
    _is_self_review_step: Callable[[dict[str, Any] | None], bool]
    _is_self_review_step_complete: Callable[..., bool]
    _build_incomplete_self_review_reminder: Callable[[dict[str, Any]], str]
    workflow_artifact_contract_satisfied: Callable[..., bool]
    _build_runtime_error_salvage_message: Callable[..., str | None]


# The runtime-turn inputs: the cycle's own inputs unchanged plus the prepared request.
def turn_inputs_from(
    cycle: RuntimeCycleInputs, *, current_runtimes: list[dict[str, Any]], request_messages: list[dict[str, Any]],
    current_tool_definitions: list[dict[str, Any]], forced_tool_calls: list[dict[str, Any]] | None,
    current_allowed_tool_names: set[str], context_snapshot: dict[str, Any],
) -> RuntimeTurnInputs:
    return RuntimeTurnInputs(
        db=cycle.db, session_id=cycle.session_id, user_id=cycle.user_id, provider_max_tokens=cycle.provider_max_tokens,
        provider_reasoning_effort=cycle.provider_reasoning_effort,
        request_timeout_seconds=cycle.request_timeout_seconds, runtime_settings=cycle.runtime_settings,
        tool_context=cycle.tool_context, request_analysis=cycle.request_analysis,
        covered_evidence_axes=cycle.covered_evidence_axes, current_step=cycle.current_step,
        current_step_index=cycle.current_step_index, current_step_iterations=cycle.current_step_iterations,
        current_step_max_iterations=cycle.current_step_max_iterations,
        current_step_tool_activity=cycle.current_step_tool_activity,
        current_step_wrapup_forced=cycle.current_step_wrapup_forced,
        workflow_artifact_ready_for_final_response=cycle.workflow_artifact_ready_for_final_response,
        active_steps=cycle.active_steps, current_turn_content=cycle.current_turn_content,
        capability_type=cycle.capability_type, context_plan=cycle.context_plan,
        turn_tool_history=cycle.turn_tool_history, step_tool_history=cycle.step_tool_history,
        executed_tool_names=cycle.executed_tool_names, tdd_cycle_state=cycle.tdd_cycle_state,
        total_tokens_in=cycle.total_tokens_in, total_tokens_out=cycle.total_tokens_out,
        consecutive_non_progress_response_count=cycle.consecutive_non_progress_response_count,
        consecutive_transitional_response_count=cycle.consecutive_transitional_response_count,
        consecutive_coding_no_execution_count=cycle.consecutive_coding_no_execution_count, messages=cycle.messages,
        chat_with_runtime_fallback=cycle.chat_with_runtime_fallback,
        normalize_runtime_chat_result=cycle.normalize_runtime_chat_result,
        dispatch_loop_runtime_response=cycle.dispatch_loop_runtime_response,
        record_usage_event=cycle.record_usage_event,
        apply_workflow_response_override=cycle.apply_workflow_response_override,
        workflow_contract_from_request_analysis=cycle.workflow_contract_from_request_analysis,
        plan_next_workflow_tool_calls=cycle.plan_next_workflow_tool_calls,
        handle_response_guards=cycle.handle_response_guards,
        persist_traced_assistant_message=cycle.persist_traced_assistant_message,
        persist_runtime_assistant_response=cycle.persist_runtime_assistant_response, event_factory=cycle.event_factory,
        is_transitional_assistant_response=cycle.is_transitional_assistant_response,
        is_transitional_tool_call_preamble=cycle.is_transitional_tool_call_preamble,
        is_non_substantive_assistant_response=cycle.is_non_substantive_assistant_response,
        looks_like_step_completion_summary=cycle.looks_like_step_completion_summary,
        allows_noop_step_completion=cycle.allows_noop_step_completion,
        build_required_tool_reminder=cycle.build_required_tool_reminder,
        build_stalled_step_message=cycle.build_stalled_step_message,
        persist_suppressed_runtime_response=cycle.persist_suppressed_runtime_response,
        persist_turn_trace=cycle.persist_turn_trace,
        build_tdd_cycle_incomplete_reminder=cycle.build_tdd_cycle_incomplete_reminder,
        build_initial_tdd_cycle_state=cycle.build_initial_tdd_cycle_state,
        is_tdd_cycle_complete=cycle.is_tdd_cycle_complete, is_tdd_cycle_step=cycle.is_tdd_cycle_step,
        _has_meaningful_coding_execution=cycle._has_meaningful_coding_execution,
        _is_probable_coding_change_request=cycle._is_probable_coding_change_request,
        _looks_like_coding_intent_only_response=cycle._looks_like_coding_intent_only_response,
        _is_self_review_step=cycle._is_self_review_step,
        _is_self_review_step_complete=cycle._is_self_review_step_complete,
        _build_incomplete_self_review_reminder=cycle._build_incomplete_self_review_reminder,
        workflow_artifact_contract_satisfied=cycle.workflow_artifact_contract_satisfied,
        _build_runtime_error_salvage_message=cycle._build_runtime_error_salvage_message,
        current_runtimes=current_runtimes, request_messages=request_messages,
        current_tool_definitions=current_tool_definitions, forced_tool_calls=forced_tool_calls,
        current_allowed_tool_names=current_allowed_tool_names, context_snapshot=context_snapshot,
    )
