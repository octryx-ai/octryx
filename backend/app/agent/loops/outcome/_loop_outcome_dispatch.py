"""Dispatch and apply turn outcomes for the standard loop."""

from __future__ import annotations

from typing import Any

from ..response._loop_message_dedupe import append_unique_system_message
from ._loop_outcome_cycle_inputs import OutcomeCycleInputs

# Loop state the dispatch hands back, starting from the cycle inputs of the same names.
_DISPATCH_STATE_KEYS = (
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
# State ``apply_no_tool_outcome`` receives and always hands back.
_NO_TOOL_STATE_KEYS = (
    "existing_thread_context",
    "duplicate_no_tool_response_count",
    "repeated_previous_step_summary_count",
    "last_no_tool_response_signature",
    "last_no_tool_response_content",
    "last_no_tool_response_step_index",
)
# Step state a no-tool outcome changes only when it advances the step.
_STEP_STATE_KEYS = (
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
)
# State ``apply_tool_outcome`` receives.
_TOOL_ARGUMENT_KEYS = (
    "existing_thread_context",
    "repeated_previous_step_summary_count",
    "workflow_artifact_ready_for_final_response",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
)
# State ``apply_tool_outcome`` hands back.
_TOOL_STATE_KEYS = (
    "context_snapshot",
    "current_allowed_tool_names",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "duplicate_no_tool_response_count",
    "executed_tool_names",
    "last_no_tool_response_content",
    "last_no_tool_response_signature",
    "last_no_tool_response_step_index",
    "latest_repo_state",
    "step_tool_history",
    "step_tool_history_index",
    "turn_tool_history",
    "existing_thread_context",
    "current_step_wrapup_forced",
    "repeated_previous_step_summary_count",
    "workflow_artifact_ready_for_final_response",
)


def _apply_no_tool(
    turn_outcome: dict[str, Any], inputs: OutcomeCycleInputs, state: dict[str, Any], events: list[Any]
) -> str:
    no_tool_state = inputs.apply_no_tool_outcome(
        turn_outcome, **{key: state[key] for key in (*_NO_TOOL_STATE_KEYS, *_STEP_STATE_KEYS)}
    )
    for key in _NO_TOOL_STATE_KEYS:
        state[key] = no_tool_state[key]
    if no_tool_state.get("event") is not None:
        events.append(no_tool_state["event"])
    no_tool_action = no_tool_state.get("action")
    if no_tool_action not in {"advance_step", "continue"}:
        return "return"
    followup_system_message = str(no_tool_state.get("followup_system_message") or "").strip()
    if followup_system_message:
        append_unique_system_message(inputs.messages, followup_system_message)
    if no_tool_action == "advance_step":
        for key in _STEP_STATE_KEYS:
            state[key] = no_tool_state[key]
    return "continue"


async def _apply_tool(
    turn_outcome: dict[str, Any], inputs: OutcomeCycleInputs, state: dict[str, Any], events: list[Any]
) -> str:
    tool_state = inputs.apply_tool_outcome(
        turn_outcome["tool_execution"],
        turn_outcome["tool_followup"],
        **{key: state[key] for key in _TOOL_ARGUMENT_KEYS},
    )
    for key in _TOOL_STATE_KEYS:
        state[key] = tool_state[key]
    if tool_state.get("event") is not None:
        events.append(tool_state["event"])
    next_forced_tool_calls = tool_state.get("forced_tool_calls")
    if next_forced_tool_calls:
        state["forced_tool_calls"] = next_forced_tool_calls
        return "continue"
    state["forced_tool_calls"] = None
    return await _apply_post_tool_action(tool_state, inputs, state, events)


async def _apply_post_tool_action(
    tool_state: dict[str, Any], inputs: OutcomeCycleInputs, state: dict[str, Any], events: list[Any]
) -> str:
    post_action = tool_state["action"]
    if post_action == "append_system_message":
        append_unique_system_message(inputs.messages, str(tool_state.get("system_message") or ""))
        followup_user_message = str(tool_state.get("followup_user_message") or "").strip()
        if followup_user_message:
            inputs.messages.append({"role": "user", "content": followup_user_message})
        await inputs.db.commit()
        return "continue"
    if post_action == "advance_step":
        append_unique_system_message(inputs.messages, str(tool_state.get("system_message") or ""))
        state["current_step_index"] = tool_state.get("next_step_index", state["current_step_index"])
        state["step_tool_history"] = tool_state.get("next_step_tool_history", state["step_tool_history"])
        if tool_state.get("next_step_tool_history_index") is not None:
            state["step_tool_history_index"] = tool_state["next_step_tool_history_index"]
        await inputs.db.commit()
        return "continue"
    if post_action == "return":
        if tool_state.get("yield_content"):
            events.append(
                inputs.event_factory(
                    role="assistant",
                    content=tool_state["yield_content"],
                    model=tool_state.get("yield_model", inputs.usage_model),
                    tokens_in=inputs.total_tokens_in,
                    tokens_out=inputs.total_tokens_out,
                )
            )
        return "return"
    return "continue"


async def dispatch_turn_outcome(turn_outcome: dict[str, Any], inputs: OutcomeCycleInputs) -> dict[str, Any]:
    state = {key: getattr(inputs, key) for key in _DISPATCH_STATE_KEYS}
    events: list[Any] = []
    if turn_outcome.get("kind") == "no_tool":
        action = _apply_no_tool(turn_outcome, inputs, state, events)
    else:
        action = await _apply_tool(turn_outcome, inputs, state, events)
    return {"action": action, "events": events, **state}


__all__ = ["dispatch_turn_outcome"]
