"""No-tool flow orchestration for the standard agent loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ._loop_no_tool import handle_no_tool_response
from ._loop_no_tool_inputs import NoToolResponseInputs

# Loop state the no-tool outcome may update; the inputs' value stays when the outcome omits it.
_CARRIED_STATE_KEYS = (
    "existing_thread_context",
    "duplicate_no_tool_response_count",
    "repeated_previous_step_summary_count",
    "last_no_tool_response_signature",
    "last_no_tool_response_content",
    "last_no_tool_response_step_index",
)


async def handle_no_tool_flow(
    inputs: NoToolResponseInputs,
    *,
    event_factory: Callable[..., Any],
    maybe_update_summary: Callable[..., Any],
) -> dict[str, Any]:
    no_tool_outcome = await handle_no_tool_response(inputs)
    outcome = {key: no_tool_outcome.get(key, getattr(inputs, key)) for key in _CARRIED_STATE_KEYS}
    outcome["followup_system_message"] = no_tool_outcome.get("followup_system_message")
    outcome["action"] = no_tool_outcome.get("action")
    yield_content = no_tool_outcome.get("yield_content")
    if yield_content:
        outcome["event"] = event_factory(
            role="assistant",
            content=yield_content,
            model=inputs.usage_model,
            tokens_in=inputs.total_tokens_in,
            tokens_out=inputs.total_tokens_out,
        )
    if outcome["action"] == "advance_step":
        outcome["current_step_index"] = no_tool_outcome.get("current_step_index", inputs.current_step_index)
        outcome["current_step_iterations"] = no_tool_outcome.get("current_step_iterations")
        outcome["current_step_tool_activity"] = no_tool_outcome.get("current_step_tool_activity")
        outcome["current_step_wrapup_forced"] = no_tool_outcome.get("current_step_wrapup_forced")
        return outcome
    if outcome["action"] == "continue":
        return outcome
    if no_tool_outcome.get("summary_needed"):
        await maybe_update_summary(inputs.session_id, inputs.db)
    return outcome
