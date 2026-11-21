"""Iteration state preparation for the standard agent loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....services.elastic_iteration import compute_elastic_step_iteration_limit
from ...core.guards.tdd_cycle import (
    augment_step_with_tdd_cycle,
    build_initial_tdd_cycle_state,
    is_tdd_cycle_step,
    restore_tdd_cycle_state,
)


def prepare_loop_iteration(
    *,
    active_steps: list[dict[str, Any]],
    current_step_index: int,
    step_tool_history: list[dict[str, Any]],
    step_tool_history_index: int | None,
    existing_thread_context: dict[str, Any] | None,
    tdd_cycle_state: dict[str, Any] | None,
    tdd_cycle_step_index: int | None,
    current_step_wrapup_forced: bool,
    runtime_settings: dict[str, Any],
    max_iterations_for_agent_step: Callable[[dict[str, Any] | None], int],
) -> dict[str, Any]:
    current_step = active_steps[current_step_index] if current_step_index < len(active_steps) else None
    if current_step is None:
        step_tool_history = []
        step_tool_history_index = None
    elif step_tool_history_index != current_step_index:
        step_tool_history = []
        step_tool_history_index = current_step_index

    current_step_for_runtime = current_step
    if current_step and is_tdd_cycle_step(current_step):
        if tdd_cycle_state is None or tdd_cycle_step_index != current_step_index:
            prior_tdd_state = (
                existing_thread_context.get("tdd_cycle") if isinstance(existing_thread_context, dict) else None
            )
            tdd_cycle_state = restore_tdd_cycle_state(
                prior_tdd_state if isinstance(prior_tdd_state, dict) else build_initial_tdd_cycle_state(current_step),
                step=current_step,
            )
            tdd_cycle_step_index = current_step_index
        current_step_for_runtime = augment_step_with_tdd_cycle(current_step, tdd_cycle_state)
    else:
        tdd_cycle_state = None
        tdd_cycle_step_index = None

    base_step_max_iterations = max_iterations_for_agent_step(current_step)
    elastic_iteration = compute_elastic_step_iteration_limit(
        step=current_step,
        base_limit=base_step_max_iterations,
        step_tool_history=step_tool_history,
        wrapup_forced=current_step_wrapup_forced,
        runtime_settings=runtime_settings,
    )
    current_step_max_iterations = int(elastic_iteration.get("effective_limit") or base_step_max_iterations)
    return {
        "current_step": current_step,
        "current_step_for_runtime": current_step_for_runtime,
        "current_step_max_iterations": current_step_max_iterations,
        "elastic_iteration": elastic_iteration,
        "step_tool_history": step_tool_history,
        "step_tool_history_index": step_tool_history_index,
        "tdd_cycle_state": tdd_cycle_state,
        "tdd_cycle_step_index": tdd_cycle_step_index,
    }
