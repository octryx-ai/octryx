"""Inputs of the no-tool response handler and the reminder text it hands to the next turn."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(kw_only=True)
class NoToolResponseInputs:
    """Inputs of ``handle_no_tool_response`` (same names as its callers pass)."""

    db: Any
    session_id: str
    request_messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    response: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    runtime: dict[str, Any]
    usage_model: str
    content: str
    assistant_msg: Any
    turn_trace: Any
    current_turn_content: str
    request_analysis: dict[str, Any]
    turn_tool_history: list[dict[str, Any]]
    required_domains: set[str]
    covered_summary_domains: set[str]
    covered_evidence_axes: set[str]
    current_step: dict[str, Any] | None
    current_step_index: int
    active_steps: list[dict[str, Any]]
    current_step_wrapup_forced: bool
    duplicate_no_tool_response_count: int
    repeated_previous_step_summary_count: int
    last_no_tool_response_signature: str | None
    last_no_tool_response_content: str
    last_no_tool_response_step_index: int | None
    existing_thread_context: dict[str, Any] | None
    assistant_no_tool_response_signature: Callable[[str], str | None]
    assistant_no_tool_response_similarity: Callable[[str, str], float]
    looks_like_step_completion_summary: Callable[[str], bool]
    detect_no_tool_stuck_loop: Callable[..., dict[str, Any] | None]
    plan_loop_recovery: Callable[..., dict[str, Any]]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_runtime_thread_context: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    runtime_settings: dict[str, Any]
    total_tokens_in: int
    total_tokens_out: int
    history_count: int
    summarize_threshold: int


def followup_text(reminder_text: str) -> str:
    """The reminder as plain text: never mutate the caller's messages list.

    ``yield_content`` / ``followup_system_message`` in the return value carry it into the next turn.
    """
    reminder = str(reminder_text or "").strip()
    if not reminder:
        return ""
    return reminder


__all__ = ["NoToolResponseInputs", "followup_text"]
