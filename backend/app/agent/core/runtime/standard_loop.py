"""Standard agent turn loop extracted from the core engine."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from ....services.loop_recovery import plan_loop_recovery
from ....services.request_analysis import (
    build_request_analysis_contract_message,
)
from ....services.stuck_loop_detector import (
    build_iteration_ceiling_event,
    detect_no_tool_stuck_loop,
    detect_tool_stuck_loop,
)
from ....services.tool_artifact import (
    build_turn_working_summary_message,
    build_within_turn_working_set_messages,
)
from ....services.workflow_contracts.artifact_contract import workflow_artifact_contract_satisfied
from ....services.workflow_contracts.contract_message import build_workflow_contract_message
from ....services.workflow_contracts.registry import (
    plan_next_workflow_tool_calls,
    workflow_contract_from_request_analysis,
)
from ....tools.tool_names import (
    CODING_CORE_TOOL_NAMES,
    CODING_PREFLIGHT_TOOL_NAMES,
    GENERAL_CORE_TOOL_NAMES,
    TURN_META_TOOL_NAMES,
    ToolName,
)
from ...loops.control._loop_final import emit_loop_final_fallback
from ...loops.control._loop_iteration_cycle import run_standard_loop_iteration
from ...loops.control._loop_iteration_shared import build_outcome_cycle_shared, build_runtime_cycle_shared
from ...loops.control._loop_recovery import (
    _apply_stuck_loop_event_to_trace,
    _augment_step_allowed_tools_for_request_analysis,
)
from ...loops.control._loop_self_review import (
    _build_incomplete_self_review_reminder,
    _is_self_review_step,
    _is_self_review_step_complete,
    _model_role_for_current_subtask,
)
from ...loops.outcome._loop_outcome_dispatch import dispatch_turn_outcome
from ...loops.outcome._loop_post_tool import handle_post_tool_outcome
from ...loops.outcome._loop_result_state import apply_no_tool_outcome, apply_runtime_turn_result, apply_tool_outcome
from ...loops.outcome._loop_tool_followup import handle_tool_followup
from ...loops.outcome._loop_turn_outcome import handle_turn_outcome
from ...loops.request._loop_preflight import (
    _has_meaningful_coding_execution,
    _is_probable_coding_change_request,
    _latest_successful_tool_result_from_history,
    _latest_successful_tool_result_from_results,
    _plan_coding_preflight_tool_calls,
    _skip_missing_evidence_for_workflow,
)
from ...loops.request._loop_request_prep import prepare_runtime_request
from ...loops.request._loop_workflow import apply_workflow_response_override, plan_forced_tool_calls_for_turn
from ...loops.response._loop_jira_bundle_report import _build_jira_sprint_bundle_report, _is_jira_sprint_planner
from ...loops.response._loop_messages import (
    _build_tool_execution_status_message,
    _build_workflow_artifact_ready_message,
    _has_awaiting_subagent_result,
    _has_pending_clarification_result,
    _looks_like_coding_intent_only_response,
)
from ...loops.response._loop_no_tool_flow import handle_no_tool_flow
from ...loops.response._loop_response_guards import handle_response_guards
from ...loops.response._loop_runtime_salvage import _build_runtime_error_salvage_message
from ...loops.runtime._loop_dispatch import dispatch_loop_runtime_response
from ...loops.runtime._loop_runtime_turn import execute_runtime_turn
from ...loops.runtime._loop_tools import execute_turn_tool_calls
from ...loops.setup._loop_bootstrap import apply_loop_bootstrap_messages
from ...loops.setup._loop_runtime_init import initialize_loop_runtime_state
from ...loops.setup._loop_setup import (
    initialize_standard_loop_state,
)
from ..guards.tdd_cycle import (
    build_initial_tdd_cycle_state,
    build_tdd_cycle_incomplete_reminder,
    is_tdd_cycle_complete,
    is_tdd_cycle_step,
)
from ..turn.turn_state import (
    fetch_thread_context_state,
    persist_runtime_assistant_response,
    persist_runtime_thread_context,
    persist_suppressed_runtime_response,
)
from ._standard_loop_runtime import (
    build_standard_loop_iteration_context,
    stream_standard_loop_iterations,
)
from .standard_loop_inputs import StandardLoopInputs, standard_loop_scope
from .summarizer import SUMMARIZE_THRESHOLD, maybe_update_summary
from .trace_runtime import persist_turn_trace

_TURN_META_TOOLS: frozenset[ToolName] = TURN_META_TOOL_NAMES
_CODING_PREFLIGHT_TOOLS: frozenset[ToolName] = CODING_PREFLIGHT_TOOL_NAMES
_PROVIDER_TOOL_LIMITS: dict[str, int] = {"copilot": 96}
_CODING_CORE_TOOL_NAMES: tuple[ToolName, ...] = CODING_CORE_TOOL_NAMES
_GENERAL_CORE_TOOL_NAMES: tuple[ToolName, ...] = GENERAL_CORE_TOOL_NAMES


# The loop's helpers, named for the iteration scope (``standard_loop_scope``); the cycle builders read them by
# these names.
_LOOP_HELPERS: dict[str, Any] = {
    "plan_loop_recovery": plan_loop_recovery,
    "build_request_analysis_contract_message": build_request_analysis_contract_message,
    "build_iteration_ceiling_event": build_iteration_ceiling_event,
    "detect_no_tool_stuck_loop": detect_no_tool_stuck_loop,
    "detect_tool_stuck_loop": detect_tool_stuck_loop,
    "build_turn_working_summary_message": build_turn_working_summary_message,
    "build_within_turn_working_set_messages": build_within_turn_working_set_messages,
    "workflow_artifact_contract_satisfied": workflow_artifact_contract_satisfied,
    "build_workflow_contract_message": build_workflow_contract_message,
    "plan_next_workflow_tool_calls": plan_next_workflow_tool_calls,
    "workflow_contract_from_request_analysis": workflow_contract_from_request_analysis,
    "CODING_CORE_TOOL_NAMES": CODING_CORE_TOOL_NAMES,
    "CODING_PREFLIGHT_TOOL_NAMES": CODING_PREFLIGHT_TOOL_NAMES,
    "GENERAL_CORE_TOOL_NAMES": GENERAL_CORE_TOOL_NAMES,
    "TURN_META_TOOL_NAMES": TURN_META_TOOL_NAMES,
    "ToolName": ToolName,
    "emit_loop_final_fallback": emit_loop_final_fallback,
    "run_standard_loop_iteration": run_standard_loop_iteration,
    "build_outcome_cycle_shared": build_outcome_cycle_shared,
    "build_runtime_cycle_shared": build_runtime_cycle_shared,
    "_apply_stuck_loop_event_to_trace": _apply_stuck_loop_event_to_trace,
    "_augment_step_allowed_tools_for_request_analysis": _augment_step_allowed_tools_for_request_analysis,
    "_build_incomplete_self_review_reminder": _build_incomplete_self_review_reminder,
    "_is_self_review_step": _is_self_review_step,
    "_is_self_review_step_complete": _is_self_review_step_complete,
    "_model_role_for_current_subtask": _model_role_for_current_subtask,
    "dispatch_turn_outcome": dispatch_turn_outcome,
    "handle_post_tool_outcome": handle_post_tool_outcome,
    "apply_no_tool_outcome": apply_no_tool_outcome,
    "apply_runtime_turn_result": apply_runtime_turn_result,
    "apply_tool_outcome": apply_tool_outcome,
    "handle_tool_followup": handle_tool_followup,
    "handle_turn_outcome": handle_turn_outcome,
    "_has_meaningful_coding_execution": _has_meaningful_coding_execution,
    "_is_probable_coding_change_request": _is_probable_coding_change_request,
    "_latest_successful_tool_result_from_history": _latest_successful_tool_result_from_history,
    "_latest_successful_tool_result_from_results": _latest_successful_tool_result_from_results,
    "_plan_coding_preflight_tool_calls": _plan_coding_preflight_tool_calls,
    "_skip_missing_evidence_for_workflow": _skip_missing_evidence_for_workflow,
    "prepare_runtime_request": prepare_runtime_request,
    "apply_workflow_response_override": apply_workflow_response_override,
    "plan_forced_tool_calls_for_turn": plan_forced_tool_calls_for_turn,
    "_build_jira_sprint_bundle_report": _build_jira_sprint_bundle_report,
    "_is_jira_sprint_planner": _is_jira_sprint_planner,
    "_build_tool_execution_status_message": _build_tool_execution_status_message,
    "_build_workflow_artifact_ready_message": _build_workflow_artifact_ready_message,
    "_has_awaiting_subagent_result": _has_awaiting_subagent_result,
    "_has_pending_clarification_result": _has_pending_clarification_result,
    "_looks_like_coding_intent_only_response": _looks_like_coding_intent_only_response,
    "handle_no_tool_flow": handle_no_tool_flow,
    "handle_response_guards": handle_response_guards,
    "_build_runtime_error_salvage_message": _build_runtime_error_salvage_message,
    "dispatch_loop_runtime_response": dispatch_loop_runtime_response,
    "execute_runtime_turn": execute_runtime_turn,
    "execute_turn_tool_calls": execute_turn_tool_calls,
    "apply_loop_bootstrap_messages": apply_loop_bootstrap_messages,
    "initialize_loop_runtime_state": initialize_loop_runtime_state,
    "initialize_standard_loop_state": initialize_standard_loop_state,
    "build_initial_tdd_cycle_state": build_initial_tdd_cycle_state,
    "build_tdd_cycle_incomplete_reminder": build_tdd_cycle_incomplete_reminder,
    "is_tdd_cycle_complete": is_tdd_cycle_complete,
    "is_tdd_cycle_step": is_tdd_cycle_step,
    "fetch_thread_context_state": fetch_thread_context_state,
    "persist_runtime_assistant_response": persist_runtime_assistant_response,
    "persist_runtime_thread_context": persist_runtime_thread_context,
    "persist_suppressed_runtime_response": persist_suppressed_runtime_response,
    "build_standard_loop_iteration_context": build_standard_loop_iteration_context,
    "stream_standard_loop_iterations": stream_standard_loop_iterations,
    "SUMMARIZE_THRESHOLD": SUMMARIZE_THRESHOLD,
    "maybe_update_summary": maybe_update_summary,
    "persist_turn_trace": persist_turn_trace,
    "_TURN_META_TOOLS": _TURN_META_TOOLS,
    "_CODING_PREFLIGHT_TOOLS": _CODING_PREFLIGHT_TOOLS,
    "_PROVIDER_TOOL_LIMITS": _PROVIDER_TOOL_LIMITS,
    "_CODING_CORE_TOOL_NAMES": _CODING_CORE_TOOL_NAMES,
    "_GENERAL_CORE_TOOL_NAMES": _GENERAL_CORE_TOOL_NAMES,
}


async def run_standard_agent_loop(inputs: StandardLoopInputs) -> AsyncGenerator[Any, None]:
    prepared = inputs.prepared
    loop_state = initialize_standard_loop_state(
        prepared=prepared,
        capability_type=prepared.capability_type,
        current_turn_content=prepared.current_turn_content,
        agent_definition=inputs.agent_definition,
        max_iterations=inputs.max_iterations,
        thinking_level=inputs.thinking_level,
        map_reasoning_effort=inputs.map_reasoning_effort,
    )
    runtime_init = initialize_loop_runtime_state(
        loop_state=loop_state,
        capability_type=prepared.capability_type,
        thinking_level=inputs.thinking_level,
        agent_definition=loop_state["agent_definition"],
        runtime_settings=prepared.runtime_settings,
        max_completion_tokens_for_run=inputs.max_completion_tokens_for_run,
    )
    messages = apply_loop_bootstrap_messages(
        messages=prepared.messages,
        agent_definition=loop_state["agent_definition"],
        injected_workflow_agent=loop_state["injected_workflow_agent"],
        request_analysis=loop_state["request_analysis"],
        workflow_contract=runtime_init["workflow_contract"],
        build_request_analysis_contract_message=build_request_analysis_contract_message,
        build_workflow_contract_message=build_workflow_contract_message,
    )
    iteration_context = build_standard_loop_iteration_context(
        scope=standard_loop_scope(
            _LOOP_HELPERS, inputs, loop_state=loop_state, runtime_init=runtime_init, messages=messages
        ),
        tool_domain_config=prepared.tool_domain_config,
        summary_domains_satisfied_by_result=inputs.summary_domains_satisfied_by_result,
        build_runtime_cycle_shared=build_runtime_cycle_shared,
        build_outcome_cycle_shared=build_outcome_cycle_shared,
        summarize_threshold=SUMMARIZE_THRESHOLD,
    )
    async for event in stream_standard_loop_iterations(
        max_iterations=loop_state["max_iterations"],
        state=iteration_context["state"],
        runtime_settings=prepared.runtime_settings,
        max_iterations_for_agent_step=inputs.max_iterations_for_agent_step,
        runtime_cycle_shared=iteration_context["runtime_cycle_shared"],
        outcome_cycle_shared=iteration_context["outcome_cycle_shared"],
        summary_domains_for_result=iteration_context["summary_domains_for_result"],
        run_standard_loop_iteration=run_standard_loop_iteration,
        emit_loop_final_fallback=emit_loop_final_fallback,
        db=inputs.db,
        session_id=inputs.session_id,
        event_factory=inputs.event_factory,
        build_runtime_error_salvage_message=_build_runtime_error_salvage_message,
    ):
        yield event


__all__ = ["run_standard_agent_loop"]
