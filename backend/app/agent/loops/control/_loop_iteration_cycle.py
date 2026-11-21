"""One-iteration driver for the standard agent loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..outcome._loop_outcome_cycle import run_outcome_cycle
from ..outcome._loop_outcome_cycle_inputs import OutcomeCycleInputs
from ..runtime._loop_runtime_cycle import run_runtime_cycle
from ..runtime._loop_runtime_cycle_inputs import RuntimeCycleInputs
from ..setup._loop_iteration_state import prepare_loop_iteration

# Loop state the runtime cycle hands back, in the order it is stored.
_RUNTIME_STATE_KEYS = (
    "request_messages",
    "current_allowed_tool_names",
    "context_snapshot",
    "workflow_contract",
    "workflow_final_answer_prompted",
    "forced_tool_calls",
    "total_tokens_in",
    "total_tokens_out",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "consecutive_non_progress_response_count",
    "consecutive_transitional_response_count",
    "consecutive_coding_no_execution_count",
)
# Loop state the runtime cycle reads unchanged.
_RUNTIME_INPUT_STATE_KEYS = (
    "messages",
    "current_step_index",
    "step_tool_history",
    "tdd_cycle_state",
    "existing_thread_context",
    "turn_diff_tracker",
    "turn_tool_history",
    "covered_evidence_axes",
    "workflow_artifact_ready_for_final_response",
    "workflow_final_answer_prompted",
    "workflow_contract",
    "forced_tool_calls",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "executed_tool_names",
    "total_tokens_in",
    "total_tokens_out",
    "consecutive_non_progress_response_count",
    "consecutive_transitional_response_count",
    "consecutive_coding_no_execution_count",
)
# Runtime-cycle results the outcome cycle reads.
_RUNTIME_RESULT_KEYS = (
    "response",
    "runtime_attempts",
    "runtime",
    "usage_model",
    "content",
    "tool_calls",
    "assistant_msg",
    "turn_trace",
    "persisted_assistant_content",
)
# Loop state the outcome cycle reads unchanged.
_OUTCOME_INPUT_STATE_KEYS = (
    "request_messages",
    "context_snapshot",
    "turn_tool_history",
    "covered_summary_domains",
    "covered_evidence_axes",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "active_steps",
    "duplicate_no_tool_response_count",
    "repeated_previous_step_summary_count",
    "last_no_tool_response_signature",
    "last_no_tool_response_content",
    "last_no_tool_response_step_index",
    "existing_thread_context",
    "total_tokens_in",
    "total_tokens_out",
    "messages",
    "current_allowed_tool_names",
    "latest_repo_state",
    "step_tool_history",
    "step_tool_history_index",
    "executed_tool_names",
    "tdd_cycle_state",
    "workflow_artifact_ready_for_final_response",
    "forced_tool_calls",
)
# Loop state the outcome dispatch hands back, in the order it is stored.
_OUTCOME_STATE_KEYS = (
    "existing_thread_context",
    "duplicate_no_tool_response_count",
    "repeated_previous_step_summary_count",
    "last_no_tool_response_signature",
    "last_no_tool_response_content",
    "last_no_tool_response_step_index",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "workflow_artifact_ready_for_final_response",
    "context_snapshot",
    "current_allowed_tool_names",
    "executed_tool_names",
    "latest_repo_state",
    "step_tool_history",
    "step_tool_history_index",
    "turn_tool_history",
    "forced_tool_calls",
)


def _prepare_iteration(
    state: dict[str, Any],
    runtime_settings: dict[str, Any] | None,
    max_iterations_for_agent_step: Callable[[dict[str, Any] | None], int],
) -> dict[str, Any]:
    """The iteration's step facts; the step histories and TDD cycle state it settles go back into ``state``."""
    iteration_state = prepare_loop_iteration(
        active_steps=state["active_steps"],
        current_step_index=state["current_step_index"],
        step_tool_history=state["step_tool_history"],
        step_tool_history_index=state["step_tool_history_index"],
        existing_thread_context=state["existing_thread_context"],
        tdd_cycle_state=state["tdd_cycle_state"],
        tdd_cycle_step_index=state["tdd_cycle_step_index"],
        current_step_wrapup_forced=state["current_step_wrapup_forced"],
        runtime_settings=runtime_settings,
        max_iterations_for_agent_step=max_iterations_for_agent_step,
    )
    for key in ("step_tool_history", "step_tool_history_index", "tdd_cycle_state", "tdd_cycle_step_index"):
        state[key] = iteration_state[key]
    return iteration_state


async def run_standard_loop_iteration(
    *,
    iteration: int,
    state: dict[str, Any],
    runtime_settings: dict[str, Any] | None,
    max_iterations_for_agent_step: Callable[[dict[str, Any] | None], int],
    runtime_cycle_shared: dict[str, Any],
    outcome_cycle_shared: dict[str, Any],
    summary_domains_for_result: Callable[[str, dict[str, Any] | None], set[str]],
    # Durable runtime parameters
    checkpoint_db: Any = None,
    checkpoint_session_id: str | None = None,
) -> dict[str, Any]:
    events: list[Any] = []
    iteration_state = _prepare_iteration(state, runtime_settings, max_iterations_for_agent_step)
    current_step = iteration_state["current_step"]
    current_step_max_iterations = iteration_state["current_step_max_iterations"]

    runtime_cycle = await run_runtime_cycle(RuntimeCycleInputs(
        iteration=iteration,
        current_step=current_step,
        current_step_for_runtime=iteration_state["current_step_for_runtime"],
        elastic_iteration=iteration_state["elastic_iteration"],
        current_step_max_iterations=current_step_max_iterations,
        **{key: state[key] for key in _RUNTIME_INPUT_STATE_KEYS},
        **runtime_cycle_shared,
    ))
    if runtime_cycle.get("event") is not None:
        events.append(runtime_cycle["event"])
    if runtime_cycle["action"] == "error":
        return {"action": "return", "events": events}

    for key in _RUNTIME_STATE_KEYS:
        state[key] = runtime_cycle[key]
    if runtime_cycle["action"] in {"continue", "return"}:
        return {"action": runtime_cycle["action"], "events": events}

    outcome_dispatch = await run_outcome_cycle(OutcomeCycleInputs(
        current_step=current_step,
        current_step_max_iterations=current_step_max_iterations,
        summary_domains_satisfied_by_result=summary_domains_for_result,
        **{key: runtime_cycle[key] for key in _RUNTIME_RESULT_KEYS},
        **{key: state[key] for key in _OUTCOME_INPUT_STATE_KEYS},
        **outcome_cycle_shared,
    ))
    for event in outcome_dispatch.get("events") or []:
        if event is not None:
            events.append(event)

    for key in _OUTCOME_STATE_KEYS:
        state[key] = outcome_dispatch[key]
    if outcome_dispatch.get("action") == "return":
        return {"action": "return", "events": events}
    await _auto_checkpoint_on_iteration_end(checkpoint_db, checkpoint_session_id, state)
    return {"action": "continue", "events": events}


__all__ = ["run_standard_loop_iteration"]

# ---------------------------------------------------------------------------
# Durable runtime: auto-checkpoint on iteration boundaries
# ---------------------------------------------------------------------------


async def _auto_checkpoint_on_iteration_end(
    checkpoint_db: Any,
    checkpoint_session_id: str | None,
    state: dict[str, Any],
) -> None:
    """Keep successful in-flight iterations unfrozen.

    ContextCheckpoint records are active freeze gates: while one is active,
    normal tool execution is intentionally blocked until `release_context`.
    Creating one after every successful iteration therefore breaks multi-tool
    agent turns. Error snapshots still use active checkpoints below because
    those represent an interrupted run boundary.
    """
    _ = (checkpoint_db, checkpoint_session_id, state)
    return


