"""Inputs of ``execute_turn_tool_calls`` and the step state it carries from one tool call to the next."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any


@dataclass(kw_only=True)
class TurnToolCallsInputs:
    """Inputs of ``execute_turn_tool_calls``; the history lists and sets are updated in place."""

    db: Any
    assistant_msg: Any
    tool_calls: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    tool_context: Any
    active_steps: list[dict[str, Any]]
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_tool_activity: bool
    current_allowed_tool_names: set[str]
    latest_repo_state: dict[str, str]
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]]
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]]
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None], set[str]]
    execute_tool: Callable[[str, dict[str, Any], Any], Any]
    execute_tool_call_for_turn: Callable[..., Any]
    turn_diff_tracker: Any
    context_snapshot: dict[str, Any]
    turn_tool_history: list[dict[str, Any]]
    step_tool_history: list[dict[str, Any]]
    step_tool_history_index: int | None
    runtime_settings: dict[str, Any]
    covered_summary_domains: set[str]
    covered_evidence_axes: set[str]
    executed_tool_names: set[str]
    tdd_cycle_state: dict[str, Any] | None


TURN_TOOL_CALLS_FIELDS = tuple(field.name for field in fields(TurnToolCallsInputs))


@dataclass(kw_only=True)
class ToolBatchState:
    """The step state one executed tool call hands to the next."""

    current_step_index: int
    current_step_iterations: int
    current_step_tool_activity: bool
    current_allowed_tool_names: set[str]
    latest_repo_state: dict[str, str]
    step_tool_history: list[dict[str, Any]]
    step_tool_history_index: int | None

    @classmethod
    def from_inputs(cls, inputs: TurnToolCallsInputs) -> ToolBatchState:
        return cls(
            current_step_index=inputs.current_step_index,
            current_step_iterations=inputs.current_step_iterations,
            current_step_tool_activity=inputs.current_step_tool_activity,
            current_allowed_tool_names=inputs.current_allowed_tool_names,
            latest_repo_state=inputs.latest_repo_state,
            step_tool_history=inputs.step_tool_history,
            step_tool_history_index=inputs.step_tool_history_index,
        )

    def apply(self, executed_tool: Any) -> None:
        """Take over the step state of an executed tool call; a step change starts a fresh step history."""
        if executed_tool.current_step_index != self.current_step_index:
            self.current_step_iterations = 0
            self.step_tool_history = []
            self.step_tool_history_index = executed_tool.current_step_index
        self.current_step_index = executed_tool.current_step_index
        self.current_step_tool_activity = executed_tool.current_step_tool_activity
        self.current_allowed_tool_names = executed_tool.current_allowed_tool_names
        self.latest_repo_state = executed_tool.latest_repo_state


__all__ = ["TURN_TOOL_CALLS_FIELDS", "ToolBatchState", "TurnToolCallsInputs"]
