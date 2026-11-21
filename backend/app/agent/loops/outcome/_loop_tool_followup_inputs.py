"""Inputs and shared helpers of ``handle_tool_followup``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ...core.runtime.trace_runtime import compact_trace_value
from ...core.runtime.turn_execution_binding import carry_turn_execution_snapshot
from ._loop_post_tool_inputs import PostToolInputs

_ResultCheck = Callable[[list[dict[str, Any]]], bool]
_SyncReport = Callable[[list[dict[str, Any]]], str | None]


@dataclass(kw_only=True)
class ToolFollowupInputs:
    """Inputs of ``handle_tool_followup``; the step counters are updated while the follow-up runs."""

    db: Any
    session_id: str
    runtime: dict[str, Any]
    response: dict[str, Any]
    request_messages: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    tool_results: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    current_turn_content: str
    content: str
    total_tokens_in: int
    total_tokens_out: int
    usage_model: str
    persisted_assistant_content: str | None
    assistant_msg: Any
    turn_trace: Any
    request_analysis: dict[str, Any]
    turn_tool_history: list[dict[str, Any]]
    step_tool_history: list[dict[str, Any]]
    current_allowed_tool_names: set[str]
    covered_evidence_axes: set[str]
    covered_summary_domains: set[str]
    required_domains: set[str]
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_wrapup_forced: bool
    current_step_tool_activity: bool
    active_steps: list[dict[str, Any]]
    repeated_previous_step_summary_count: int
    latest_repo_state: dict[str, str]
    executed_tool_names: set[str]
    context_plan: Any
    tdd_cycle_state: dict[str, Any] | None
    workflow_artifact_ready_for_final_response: bool
    existing_thread_context: Any
    runtime_attempts: list[dict[str, Any]]
    runtime_settings: dict[str, Any]
    agent_definition: Any
    event_factory: Callable[..., Any]
    detect_tool_stuck_loop: Callable[..., Any]
    _apply_stuck_loop_event_to_trace: Callable[..., Any]
    persist_runtime_thread_context: Callable[..., Any]
    plan_next_workflow_tool_calls: Callable[..., list[dict[str, Any]]]
    persist_traced_assistant_message: Callable[..., Any]
    persist_synthesized_tool_assistant: Callable[..., Any]
    fetch_thread_context_state: Callable[..., Any]
    format_repository_noop_sync_report: _SyncReport
    format_repository_knowledge_sync_report: _SyncReport
    format_recent_bitbucket_commits_report: Callable[[dict[str, Any]], str]
    has_pending_approval_result: _ResultCheck
    _has_awaiting_subagent_result: _ResultCheck
    _has_pending_clarification_result: _ResultCheck
    _latest_successful_tool_result_from_results: Callable[[list[dict[str, Any]], str], dict[str, Any] | None]
    _is_jira_sprint_planner: Callable[[dict[str, Any] | None], bool]
    _build_jira_sprint_bundle_report: Callable[[dict[str, Any]], str | None]
    build_iteration_ceiling_event: Callable[..., dict[str, Any]]
    plan_loop_recovery: Callable[..., dict[str, Any]]
    handle_post_tool_outcome: Callable[[PostToolInputs], Awaitable[dict[str, Any]]]
    # Round state derived while the follow-up runs; never passed by callers.
    tool_event: Any = field(default=None, init=False)
    stuck_loop_event: Any = field(default=None, init=False)
    workflow_contract: dict[str, Any] | None = field(default=None, init=False)


def sync_turn_trace_context(run: ToolFollowupInputs) -> None:
    run.turn_trace.context_snapshot_json = carry_turn_execution_snapshot(
        run.turn_trace.context_snapshot_json,
        compact_trace_value(run.context_snapshot, trace_limits=run.runtime_settings),
    )


def followup_result(run: ToolFollowupInputs, action: str, **extra: Any) -> dict[str, Any]:
    """Action dict carrying the tool event, thread context and step counters; ``extra`` adds or overrides keys."""
    return {
        "action": action,
        "event": run.tool_event,
        "existing_thread_context": run.existing_thread_context,
        "current_step_iterations": run.current_step_iterations,
        "current_step_tool_activity": run.current_step_tool_activity,
        "repeated_previous_step_summary_count": run.repeated_previous_step_summary_count,
        **extra,
    }
