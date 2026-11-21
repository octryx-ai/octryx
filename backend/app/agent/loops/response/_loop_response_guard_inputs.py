"""Inputs of the pre-persistence response guards and the counters they hand back."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(kw_only=True)
class ResponseGuardInputs:
    """Inputs of ``handle_response_guards`` (same names and defaults as its callers pass)."""

    db: Any
    session_id: str
    runtime: dict[str, Any]
    response: dict[str, Any]
    request_messages: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    runtime_settings: dict[str, Any]
    usage_model: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    current_tool_definitions: list[dict[str, Any]]
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_tool_activity: bool
    current_step_wrapup_forced: bool
    active_steps: list[dict[str, Any]]
    current_turn_content: str
    capability_type: str
    tool_context: Any
    request_analysis: dict[str, Any]
    context_plan: Any
    turn_tool_history: list[dict[str, Any]]
    step_tool_history: list[dict[str, Any]]
    executed_tool_names: set[str]
    covered_evidence_axes: set[str]
    workflow_contract: dict[str, Any] | None
    workflow_artifact_ready_for_final_response: bool = False
    tdd_cycle_state: dict[str, Any] | None
    total_tokens_in: int
    total_tokens_out: int
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    consecutive_coding_no_execution_count: int
    is_transitional_assistant_response: Callable[[str, list[dict[str, Any]] | None, bool], bool]
    is_transitional_tool_call_preamble: Callable[[str, list[dict[str, Any]] | None], bool]
    is_non_substantive_assistant_response: Callable[[str, list[dict[str, Any]] | None], bool]
    looks_like_step_completion_summary: Callable[[str], bool]
    allows_noop_step_completion: Callable[[dict[str, Any] | None, str], bool]
    build_required_tool_reminder: Callable[[dict[str, Any]], str]
    build_stalled_step_message: Callable[[dict[str, Any]], str]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_turn_trace: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    build_tdd_cycle_incomplete_reminder: Callable[[dict[str, Any], dict[str, Any]], str]
    build_initial_tdd_cycle_state: Callable[[], dict[str, Any]]
    is_tdd_cycle_complete: Callable[[dict[str, Any] | None], bool]
    is_tdd_cycle_step: Callable[[dict[str, Any] | None], bool]
    _has_meaningful_coding_execution: Callable[[list[dict[str, Any]]], bool]
    _is_probable_coding_change_request: Callable[..., bool]
    _looks_like_coding_intent_only_response: Callable[[str], bool]
    _is_self_review_step: Callable[[dict[str, Any] | None], bool]
    _is_self_review_step_complete: Callable[[dict[str, Any] | None, list[dict[str, Any]]], bool]
    _build_incomplete_self_review_reminder: Callable[[dict[str, Any]], str]
    workflow_artifact_contract_satisfied: Callable[..., bool]

    def turn_kwargs(self) -> dict[str, Any]:
        """The runtime/turn keywords every delegated guard takes."""
        return {
            "db": self.db,
            "session_id": self.session_id,
            "runtime": self.runtime,
            "response": self.response,
            "request_messages": self.request_messages,
            "messages": self.messages,
            "context_snapshot": self.context_snapshot,
            "runtime_attempts": self.runtime_attempts,
            "runtime_settings": self.runtime_settings,
            "usage_model": self.usage_model,
        }

    def has_followup_steps(self) -> bool:
        return bool(self.current_step and self.current_step_index < len(self.active_steps) - 1)

    def counts(self, *, non_progress_bump: int = 0) -> dict[str, int]:
        return {
            "consecutive_non_progress_response_count": self.consecutive_non_progress_response_count + non_progress_bump,
            "consecutive_coding_no_execution_count": self.consecutive_coding_no_execution_count,
            "consecutive_transitional_response_count": self.consecutive_transitional_response_count,
        }

    def take_counts(self, outcome: dict[str, Any], *keys: str) -> None:
        """Adopt the counters a guard that let the reply pass handed back (missing keys keep their value)."""
        for key in keys:
            setattr(self, key, outcome.get(key, getattr(self, key)))


__all__ = ["ResponseGuardInputs"]
