"""Inputs of ``run_outcome_cycle``, shared by the turn outcome, its dispatch and the no-tool and tool branches."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from typing import Any

from ..response._loop_no_tool_inputs import NoToolResponseInputs
from ..runtime._loop_runtime_turn_inputs import input_values
from ..runtime._loop_tool_calls_inputs import TURN_TOOL_CALLS_FIELDS, TurnToolCallsInputs
from ._loop_post_tool_inputs import PostToolInputs
from ._loop_tool_followup_inputs import ToolFollowupInputs


@dataclass(kw_only=True)
class OutcomeCycleInputs:
    """The inputs of ``run_outcome_cycle``; unknown or missing names raise ``TypeError``."""

    db: Any
    session_id: str
    request_messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    response: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    runtime: dict[str, Any]
    usage_model: str
    content: str
    tool_calls: list[dict[str, Any]]
    assistant_msg: Any
    turn_trace: Any
    current_turn_content: str
    request_analysis: dict[str, Any] | None
    turn_tool_history: list[dict[str, Any]]
    required_domains: set[str]
    covered_summary_domains: set[str]
    covered_evidence_axes: set[str]
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_tool_activity: bool
    current_step_wrapup_forced: bool
    active_steps: list[dict[str, Any]]
    duplicate_no_tool_response_count: int
    repeated_previous_step_summary_count: int
    last_no_tool_response_signature: str | None
    last_no_tool_response_content: str
    last_no_tool_response_step_index: int | None
    existing_thread_context: dict[str, Any] | None
    runtime_settings: dict[str, Any] | None
    total_tokens_in: int
    total_tokens_out: int
    history_count: int
    summarize_threshold: int
    messages: list[dict[str, Any]]
    tool_context: Any
    current_allowed_tool_names: set[str]
    latest_repo_state: dict[str, str]
    turn_diff_tracker: Any
    step_tool_history: list[dict[str, Any]]
    step_tool_history_index: int | None
    executed_tool_names: set[str]
    tdd_cycle_state: dict[str, Any] | None
    persisted_assistant_content: str | None
    context_plan: Any
    workflow_artifact_ready_for_final_response: bool
    agent_definition: Any
    forced_tool_calls: list[dict[str, Any]] | None
    assistant_no_tool_response_signature: Callable[[str], str | None]
    assistant_no_tool_response_similarity: Callable[[str, str], float]
    looks_like_step_completion_summary: Callable[[str], bool]
    detect_no_tool_stuck_loop: Callable[..., dict[str, Any] | None]
    plan_loop_recovery: Callable[..., dict[str, Any] | None]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_runtime_thread_context: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    event_factory: Callable[..., Any]
    maybe_update_summary: Callable[..., Any]
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]]
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]]
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None], set[str]]
    execute_tool: Callable[[str, dict[str, Any], Any], Any]
    execute_tool_call_for_turn: Callable[..., Any]
    detect_tool_stuck_loop: Callable[..., dict[str, Any] | None]
    _apply_stuck_loop_event_to_trace: Callable[..., dict[str, Any] | None]
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]]
    persist_synthesized_tool_assistant: Callable[..., Any]
    fetch_thread_context_state: Callable[..., dict[str, Any] | None]
    format_repository_noop_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_repository_knowledge_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_recent_bitbucket_commits_report: Callable[[dict[str, Any]], str]
    has_pending_approval_result: Callable[[list[dict[str, Any]]], bool]
    _has_pending_clarification_result: Callable[[list[dict[str, Any]]], bool]
    _has_awaiting_subagent_result: Callable[[dict[str, Any] | None], bool]
    _latest_successful_tool_result_from_results: Callable[..., dict[str, Any] | None]
    _is_jira_sprint_planner: Callable[[dict[str, Any] | None], bool]
    _build_jira_sprint_bundle_report: Callable[..., str | None]
    build_iteration_ceiling_event: Callable[..., Any]
    handle_post_tool_outcome: Callable[[PostToolInputs], Awaitable[dict[str, Any]]]
    execute_turn_tool_calls: Callable[[TurnToolCallsInputs], Awaitable[dict[str, Any]]]
    handle_no_tool_flow: Callable[..., Awaitable[dict[str, Any]]]
    handle_tool_followup: Callable[[ToolFollowupInputs], Awaitable[dict[str, Any]]]
    handle_turn_outcome: Callable[[OutcomeCycleInputs], Awaitable[dict[str, Any]]]
    dispatch_turn_outcome: Callable[[dict[str, Any], OutcomeCycleInputs], Awaitable[dict[str, Any]]]
    apply_no_tool_outcome: Callable[..., dict[str, Any]]
    apply_tool_outcome: Callable[..., dict[str, Any]]


# Tool-execution state the follow-up takes from the executed batch instead of the cycle inputs.
_EXECUTION_STATE_KEYS = (
    "context_snapshot",
    "tool_results",
    "turn_tool_history",
    "step_tool_history",
    "current_allowed_tool_names",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "latest_repo_state",
    "executed_tool_names",
)
_FOLLOWUP_INPUT_FIELDS = tuple(
    field.name for field in fields(ToolFollowupInputs) if field.init and field.name not in _EXECUTION_STATE_KEYS
)
_NO_TOOL_FIELDS = tuple(field.name for field in fields(NoToolResponseInputs))


def no_tool_inputs_from(inputs: OutcomeCycleInputs) -> NoToolResponseInputs:
    """The no-tool response inputs: the cycle's inputs of the same names."""
    return NoToolResponseInputs(**input_values(inputs, _NO_TOOL_FIELDS))


def tool_calls_inputs_from(inputs: OutcomeCycleInputs) -> TurnToolCallsInputs:
    """The tool-batch inputs: the cycle's inputs of the same names."""
    return TurnToolCallsInputs(**input_values(inputs, TURN_TOOL_CALLS_FIELDS))


def tool_followup_inputs_from(inputs: OutcomeCycleInputs, tool_execution: dict[str, Any]) -> ToolFollowupInputs:
    """The follow-up inputs: the executed batch's state plus the cycle's other inputs."""
    return ToolFollowupInputs(
        **input_values(inputs, _FOLLOWUP_INPUT_FIELDS),
        **{key: tool_execution[key] for key in _EXECUTION_STATE_KEYS},
    )


__all__ = ["OutcomeCycleInputs", "no_tool_inputs_from", "tool_calls_inputs_from", "tool_followup_inputs_from"]
