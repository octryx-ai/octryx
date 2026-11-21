"""Run one standard-loop runtime cycle and normalize the resulting state."""

from __future__ import annotations

from typing import Any

from ._loop_runtime_cycle_inputs import RuntimeCycleInputs, turn_inputs_from

# State ``apply_runtime_turn_result`` normalizes, in the order the cycle returns it after the prompted flag
# (``context_snapshot`` and ``workflow_contract`` come first, before that flag).
_TURN_STATE_KEYS = (
    "context_snapshot",
    "workflow_contract",
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
    "runtime",
    "response",
    "runtime_attempts",
    "content",
    "tool_calls",
    "usage_model",
    "persisted_assistant_content",
    "assistant_msg",
    "turn_trace",
)


def _cycle_action(raw_action: Any) -> str:
    if raw_action in {"advance_step", "continue"}:
        return "continue"
    if raw_action == "return":
        return "return"
    return "none"


async def run_runtime_cycle(inputs: RuntimeCycleInputs) -> dict[str, Any]:
    request_prep = inputs.prepare_runtime_request(inputs)
    current_allowed_tool_names = request_prep["current_allowed_tool_names"]
    request_messages = request_prep["request_messages"]
    context_snapshot = request_prep["context_snapshot"]
    forced_tool_calls = request_prep["forced_tool_calls"]
    workflow_contract = request_prep["workflow_contract"]
    workflow_final_answer_prompted = request_prep["workflow_final_answer_prompted"]

    runtime_turn = await inputs.execute_runtime_turn(turn_inputs_from(
        inputs,
        current_runtimes=request_prep["current_runtimes"],
        request_messages=request_messages,
        current_tool_definitions=request_prep["current_tool_definitions"],
        forced_tool_calls=forced_tool_calls,
        current_allowed_tool_names=current_allowed_tool_names,
        context_snapshot=context_snapshot,
    ))
    event = runtime_turn.get("event")
    raw_action = runtime_turn.get("action")
    if raw_action == "error":
        return {"action": "error", "event": event}

    runtime_turn_state = inputs.apply_runtime_turn_result(
        runtime_turn,
        total_tokens_in=inputs.total_tokens_in,
        total_tokens_out=inputs.total_tokens_out,
        forced_tool_calls=forced_tool_calls,
        context_snapshot=context_snapshot,
        current_step_index=inputs.current_step_index,
        current_step_iterations=inputs.current_step_iterations,
        current_step_tool_activity=inputs.current_step_tool_activity,
        current_step_wrapup_forced=inputs.current_step_wrapup_forced,
        consecutive_non_progress_response_count=inputs.consecutive_non_progress_response_count,
        consecutive_transitional_response_count=inputs.consecutive_transitional_response_count,
        consecutive_coding_no_execution_count=inputs.consecutive_coding_no_execution_count,
        workflow_contract=workflow_contract,
    )
    state = {key: runtime_turn_state[key] for key in _TURN_STATE_KEYS}
    return {
        "action": _cycle_action(raw_action),
        "event": event,
        "request_messages": request_messages,
        "current_allowed_tool_names": current_allowed_tool_names,
        "context_snapshot": state["context_snapshot"],
        "workflow_contract": state["workflow_contract"],
        "workflow_final_answer_prompted": workflow_final_answer_prompted,
        **{key: state[key] for key in _TURN_STATE_KEYS[2:]},
    }


__all__ = ["run_runtime_cycle"]
