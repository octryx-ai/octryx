"""State application helpers for standard loop turn results."""

from __future__ import annotations

from typing import Any, TypedDict


class RuntimeTurnResult(TypedDict, total=False):
    """Result dict shape from apply_runtime_turn_result — matches _loop_runtime_cycle expectations."""

    total_tokens_in: int
    total_tokens_out: int
    forced_tool_calls: list[dict[str, Any]] | None
    context_snapshot: dict[str, Any]
    current_step_index: int
    current_step_iterations: int
    current_step_tool_activity: bool
    current_step_wrapup_forced: bool
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    consecutive_coding_no_execution_count: int
    runtime: dict[str, Any]
    response: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    content: str
    tool_calls: list[dict[str, Any]] | None
    workflow_contract: dict[str, Any] | None
    usage_model: str
    persisted_assistant_content: str | None
    assistant_msg: Any
    turn_trace: Any
    action: str


def apply_runtime_turn_result(
    runtime_turn: dict[str, Any],
    *,
    total_tokens_in: int,
    total_tokens_out: int,
    forced_tool_calls,
    context_snapshot: dict[str, Any],
    current_step_index: int,
    current_step_iterations: int,
    current_step_tool_activity: bool,
    current_step_wrapup_forced: bool,
    consecutive_non_progress_response_count: int,
    consecutive_transitional_response_count: int,
    consecutive_coding_no_execution_count: int,
    workflow_contract,
) -> RuntimeTurnResult:
    return {
        "total_tokens_in": runtime_turn.get("total_tokens_in", total_tokens_in),
        "total_tokens_out": runtime_turn.get("total_tokens_out", total_tokens_out),
        "forced_tool_calls": runtime_turn.get("forced_tool_calls", forced_tool_calls),
        "context_snapshot": runtime_turn.get("context_snapshot", context_snapshot),
        "current_step_index": runtime_turn.get("current_step_index", current_step_index),
        "current_step_iterations": runtime_turn.get("current_step_iterations", current_step_iterations),
        "current_step_tool_activity": runtime_turn.get("current_step_tool_activity", current_step_tool_activity),
        "current_step_wrapup_forced": runtime_turn.get("current_step_wrapup_forced", current_step_wrapup_forced),
        "consecutive_non_progress_response_count": runtime_turn.get(
            "consecutive_non_progress_response_count",
            consecutive_non_progress_response_count,
        ),
        "consecutive_transitional_response_count": runtime_turn.get(
            "consecutive_transitional_response_count",
            consecutive_transitional_response_count,
        ),
        "consecutive_coding_no_execution_count": runtime_turn.get(
            "consecutive_coding_no_execution_count",
            consecutive_coding_no_execution_count,
        ),
        "runtime": runtime_turn.get("runtime"),
        "response": runtime_turn.get("response"),
        "runtime_attempts": runtime_turn.get("runtime_attempts", []),
        "content": runtime_turn.get("content", ""),
        "tool_calls": runtime_turn.get("tool_calls"),
        "workflow_contract": runtime_turn.get("workflow_contract", workflow_contract),
        "usage_model": runtime_turn.get("usage_model", ""),
        "persisted_assistant_content": runtime_turn.get("persisted_assistant_content"),
        "assistant_msg": runtime_turn.get("assistant_msg"),
        "turn_trace": runtime_turn.get("turn_trace"),
        "action": runtime_turn.get("action"),
    }


def apply_no_tool_outcome(
    turn_outcome: dict[str, Any],
    *,
    existing_thread_context,
    duplicate_no_tool_response_count: int,
    repeated_previous_step_summary_count: int,
    last_no_tool_response_signature: str | None,
    last_no_tool_response_content: str,
    last_no_tool_response_step_index: int | None,
    current_step_index: int,
    current_step_iterations: int,
    current_step_tool_activity: bool,
    current_step_wrapup_forced: bool,
) -> dict[str, Any]:
    return {
        "existing_thread_context": turn_outcome.get("existing_thread_context", existing_thread_context),
        "duplicate_no_tool_response_count": turn_outcome.get(
            "duplicate_no_tool_response_count",
            duplicate_no_tool_response_count,
        ),
        "repeated_previous_step_summary_count": turn_outcome.get(
            "repeated_previous_step_summary_count",
            repeated_previous_step_summary_count,
        ),
        "last_no_tool_response_signature": turn_outcome.get(
            "last_no_tool_response_signature",
            last_no_tool_response_signature,
        ),
        "last_no_tool_response_content": turn_outcome.get(
            "last_no_tool_response_content",
            last_no_tool_response_content,
        ),
        "last_no_tool_response_step_index": turn_outcome.get(
            "last_no_tool_response_step_index",
            last_no_tool_response_step_index,
        ),
        "current_step_index": turn_outcome.get("current_step_index", current_step_index),
        "current_step_iterations": turn_outcome.get("current_step_iterations", current_step_iterations),
        "current_step_tool_activity": turn_outcome.get("current_step_tool_activity", current_step_tool_activity),
        "current_step_wrapup_forced": turn_outcome.get("current_step_wrapup_forced", current_step_wrapup_forced),
        "followup_system_message": turn_outcome.get("followup_system_message"),
        "action": turn_outcome.get("action"),
        "event": turn_outcome.get("event"),
    }


def apply_tool_outcome(
    tool_execution: dict[str, Any],
    tool_followup: dict[str, Any],
    *,
    existing_thread_context,
    repeated_previous_step_summary_count: int,
    workflow_artifact_ready_for_final_response: bool,
    current_step_iterations: int,
    current_step_tool_activity: bool,
    current_step_wrapup_forced: bool,
) -> dict[str, Any]:
    return {
        "context_snapshot": tool_execution["context_snapshot"],
        "current_allowed_tool_names": tool_execution["current_allowed_tool_names"],
        "current_step_index": tool_execution["current_step_index"],
        "current_step_iterations": tool_followup.get("current_step_iterations", current_step_iterations),
        "current_step_tool_activity": tool_followup.get("current_step_tool_activity", current_step_tool_activity),
        "duplicate_no_tool_response_count": tool_execution["duplicate_no_tool_response_count"],
        "executed_tool_names": tool_execution["executed_tool_names"],
        "last_no_tool_response_content": tool_execution["last_no_tool_response_content"],
        "last_no_tool_response_signature": tool_execution["last_no_tool_response_signature"],
        "last_no_tool_response_step_index": tool_execution["last_no_tool_response_step_index"],
        "latest_repo_state": tool_execution["latest_repo_state"],
        "step_tool_history": tool_execution["step_tool_history"],
        "step_tool_history_index": tool_execution["step_tool_history_index"],
        "turn_tool_history": tool_execution["turn_tool_history"],
        "existing_thread_context": tool_followup.get("existing_thread_context", existing_thread_context),
        "current_step_wrapup_forced": tool_followup.get("current_step_wrapup_forced", current_step_wrapup_forced),
        "repeated_previous_step_summary_count": tool_followup.get(
            "repeated_previous_step_summary_count",
            repeated_previous_step_summary_count,
        ),
        "workflow_artifact_ready_for_final_response": tool_followup.get(
            "workflow_artifact_ready_for_final_response",
            workflow_artifact_ready_for_final_response,
        ),
        "forced_tool_calls": tool_followup.get("forced_tool_calls"),
        "action": tool_followup.get("action"),
        "event": tool_followup.get("event"),
        "yield_content": tool_followup.get("yield_content"),
        "yield_model": tool_followup.get("yield_model"),
        "system_message": tool_followup.get("system_message"),
        "followup_user_message": tool_followup.get("followup_user_message"),
        "next_step_index": tool_followup.get("current_step_index"),
        "next_step_tool_history": tool_followup.get("step_tool_history"),
        "next_step_tool_history_index": tool_followup.get("step_tool_history_index"),
    }
