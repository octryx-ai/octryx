"""Required-tool step guard of the standard loop.

A step whose tool use is required (``agent/core/guards/step_tool_requirement.py``)
may not complete with a text-only reply: the first one gets a reminder; on the final
step a second one (or the step's attempt limit) ends the turn with an explicit stop
answer whose trace carries the closed runtime stop reason. A non-final step that
reaches its attempt limit advances. One trace is written per model
response: a response that ends the turn is recorded only on the stop answer's trace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ....services.session.turn_execution_snapshot import RUNTIME_STOP_STEP_STALLED, RUNTIME_STOP_STEP_TOOL_REQUIRED
from ...core.guards.step_tool_requirement import build_tool_required_stop, step_tool_use, tool_requirement_declined
from ._loop_message_dedupe import append_unique_assistant_context, append_unique_system_message

if TYPE_CHECKING:
    from ._loop_coding_guard_nudges import CodingGuardInputs


async def handle_required_tool_step_response(inputs: CodingGuardInputs) -> dict[str, Any] | None:
    """Return the loop action for a required-tool step reply, or ``None`` when it does not apply."""
    current_step = inputs.current_step
    content = inputs.content
    tool_use_required, tool_use_source = step_tool_use(current_step)
    if not (
        current_step
        and tool_use_required
        and not inputs.current_step_tool_activity
        and not inputs.tool_calls
        and not inputs.workflow_artifact_ready_for_final_response
        and not inputs.allows_noop_step_completion(current_step, content or "")
    ):
        return None
    reminder = inputs.build_required_tool_reminder(current_step)
    attempts_used = inputs.current_step_iterations + 1
    append_unique_assistant_context(inputs.messages, content or "")
    is_final_step = inputs.current_step_index >= len(inputs.active_steps) - 1
    declined = is_final_step and tool_requirement_declined(attempts_used)
    stops_here = is_final_step and (declined or attempts_used >= inputs.current_step_max_iterations)
    # One trace per model response: when this response ends the run, the stop
    # answer's trace below records it (content, attempts, usage) — a separate
    # suppressed trace would count the same call twice in trace-based analytics.
    if not stops_here:
        await _persist_suppressed_attempt(inputs, tool_use_source=tool_use_source, attempts_used=attempts_used)
    if attempts_used >= inputs.current_step_max_iterations or declined:
        if inputs.current_step_index < len(inputs.active_steps) - 1:
            append_unique_system_message(inputs.messages, reminder)
            await inputs.db.commit()
            return _advance_step_result(inputs, yield_content=content or reminder)
        stalled_content = await _persist_stalled_final_step(
            inputs, declined=declined, tool_use_source=tool_use_source, attempts_used=attempts_used
        )
        return {
            "action": "return",
            "yield_content": stalled_content,
            "yield_model": inputs.usage_model,
            "consecutive_transitional_response_count": inputs.consecutive_transitional_response_count,
        }

    append_unique_system_message(inputs.messages, reminder)
    await inputs.db.commit()
    return {
        "action": "continue",
        "yield_content": content or reminder,
        "yield_model": inputs.usage_model,
        "current_step_iterations": attempts_used,
        "consecutive_transitional_response_count": inputs.consecutive_transitional_response_count,
    }


def _advance_step_result(inputs: CodingGuardInputs, *, yield_content: str) -> dict[str, Any]:
    return {
        "action": "advance_step",
        "yield_content": yield_content,
        "yield_model": inputs.usage_model,
        "current_step_index": inputs.current_step_index + 1,
        "current_step_iterations": 0,
        "current_step_tool_activity": False,
        "current_step_wrapup_forced": False,
        "consecutive_transitional_response_count": inputs.consecutive_transitional_response_count,
    }


async def _persist_suppressed_attempt(inputs: CodingGuardInputs, *, tool_use_source: Any, attempts_used: int) -> None:
    await inputs.persist_turn_trace(
        db=inputs.db,
        session_id=inputs.session_id,
        message_id=None,
        provider=inputs.runtime["provider_name"],
        model=inputs.usage_model,
        input_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        tool_trace=[],
        raw_output={
            "content": inputs.content,
            "tool_calls": [],
            "runtime_attempts": inputs.runtime_attempts,
            "suppressed_for_missing_required_tool_use": True,
            "tool_use_source": tool_use_source,
            "step_attempt": attempts_used,
        },
        usage=inputs.response.get("usage", {}),
        trace_limits=inputs.runtime_settings,
    )


async def _persist_stalled_final_step(
    inputs: CodingGuardInputs, *, declined: bool, tool_use_source: Any, attempts_used: int
) -> str:
    """Persist the explicit stop answer of the final step; returns its content."""
    current_step = inputs.current_step
    stalled_content = (
        build_tool_required_stop(current_step) if declined else inputs.build_stalled_step_message(current_step)
    )
    usage = inputs.response.get("usage", {})
    await inputs.persist_traced_assistant_message(
        db=inputs.db,
        session_id=inputs.session_id,
        content=stalled_content,
        provider=inputs.runtime["provider_name"],
        model=inputs.usage_model,
        input_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        tool_trace=[],
        raw_output={
            "content": inputs.content,
            "tool_calls": [],
            "runtime_attempts": inputs.runtime_attempts,
            "stalled_final_step": True,
            "suppressed_for_missing_required_tool_use": True,
            "tool_requirement_declined": declined,
            "tool_use_source": tool_use_source,
            "step_attempt": attempts_used,
            "step_name": current_step.get("name"),
        },
        usage=usage,
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        trace_limits=inputs.runtime_settings,
        runtime_stop_reason=RUNTIME_STOP_STEP_TOOL_REQUIRED if declined else RUNTIME_STOP_STEP_STALLED,
    )
    return stalled_content
