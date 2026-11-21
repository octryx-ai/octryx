"""Inputs of ``handle_post_tool_outcome``: the tool round, the turn state and the loop collaborators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_ResultCheck = Callable[[list[dict[str, Any]]], bool]


@dataclass(kw_only=True)
class PostToolInputs:
    """Inputs of ``handle_post_tool_outcome`` (same names as the loop passes them)."""

    db: Any
    session_id: str
    runtime: dict[str, Any]
    response: dict[str, Any]
    request_messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    tool_results: list[dict[str, Any]]
    current_user_message: str
    content: str
    total_tokens_in: int
    total_tokens_out: int
    usage_model: str
    event_factory: Callable[..., Any]
    fetch_thread_context_state: Callable[..., Any]
    persist_synthesized_tool_assistant: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    runtime_attempts: list[dict[str, Any]]
    request_analysis: dict[str, Any]
    turn_tool_history: list[dict[str, Any]]
    workflow_contract: dict[str, Any] | None
    workflow_artifact_ready_for_final_response: bool
    current_allowed_tool_names: set[str]
    covered_evidence_axes: set[str]
    current_step: dict[str, Any] | None
    tdd_cycle_state: dict[str, Any] | None
    current_step_index: int
    active_steps: list[dict[str, Any]]
    current_step_wrapup_forced: bool
    current_step_iterations: int
    current_step_max_iterations: int
    runtime_settings: dict[str, Any]
    required_domains: set[str]
    covered_summary_domains: set[str]
    agent_definition: Any
    executed_tool_names: set[str]
    context_plan: Any
    has_pending_approval_result: _ResultCheck
    _has_awaiting_subagent_result: _ResultCheck
    _has_pending_clarification_result: _ResultCheck
    _latest_successful_tool_result_from_results: Callable[[list[dict[str, Any]], str], dict[str, Any] | None]
    _is_jira_sprint_planner: Callable[[dict[str, Any] | None], bool]
    _build_jira_sprint_bundle_report: Callable[[dict[str, Any]], str | None]
    format_repository_noop_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_repository_knowledge_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_recent_bitbucket_commits_report: Callable[[dict[str, Any]], str]
    build_iteration_ceiling_event: Callable[..., dict[str, Any]]
    plan_loop_recovery: Callable[..., dict[str, Any]]
    stuck_loop_event: dict[str, Any] | None
    is_tdd_cycle_step: Callable[[dict[str, Any] | None], bool]
    is_tdd_cycle_complete: Callable[[dict[str, Any] | None], bool]


__all__ = ["PostToolInputs"]
