"""Repeated no-tool replies: stuck-loop detection, recovery planning and its persistence."""

from __future__ import annotations

from typing import Any

from ..control._loop_recovery import _apply_loop_recovery_to_context, _apply_stuck_loop_event_to_trace
from ._loop_no_tool_inputs import NoToolResponseInputs, followup_text


def _plan_repeat_recovery(
    inputs: NoToolResponseInputs,
    *,
    content: str,
    no_tool_signature: str | None,
    no_tool_similarity: float,
    duplicate_count: int,
    repeated_count: int,
    repeated: bool,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Detect the stuck loop, plan its recovery; returns (recovery, reminder, trace payload)."""
    stuck_loop_event = inputs.detect_no_tool_stuck_loop(
        step=inputs.current_step,
        step_index=inputs.current_step_index,
        current_content=content or "",
        current_signature=no_tool_signature,
        previous_content=inputs.last_no_tool_response_content,
        previous_signature=inputs.last_no_tool_response_signature,
        similarity=no_tool_similarity,
        duplicate_count=duplicate_count,
        repeated_previous_step_summary_count=repeated_count,
        repeated_previous_step_summary=repeated,
        runtime_settings=inputs.runtime_settings,
    )
    compact_stuck_loop_event = _apply_stuck_loop_event_to_trace(
        context_snapshot=inputs.context_snapshot,
        turn_trace=inputs.turn_trace,
        event=stuck_loop_event,
        runtime_settings=inputs.runtime_settings,
    )
    current_step = inputs.current_step
    recovery = inputs.plan_loop_recovery(
        event=stuck_loop_event,
        step=current_step,
        has_followup_steps=bool(current_step and inputs.current_step_index < len(inputs.active_steps) - 1),
        wrapup_forced=inputs.current_step_wrapup_forced,
    )
    compact_recovery = _apply_loop_recovery_to_context(
        context_snapshot=inputs.context_snapshot,
        recovery=recovery,
        runtime_settings=inputs.runtime_settings,
    )
    reminder = followup_text(str(recovery.get("system_message") or ""))
    messages_payload = {
        "content": content,
        "tool_calls": [],
        "runtime_attempts": inputs.runtime_attempts,
        "stuck_loop_detector": compact_stuck_loop_event,
        "loop_recovery": compact_recovery,
    }
    if repeated:
        messages_payload["suppressed_as_repeated_previous_step_summary"] = True
    return recovery, reminder, messages_payload


async def _persist_repeat(
    inputs: NoToolResponseInputs, *, content: str, reminder: str, messages_payload: dict[str, Any], repeated: bool
) -> Any:
    """Persist the suppressed reply and the thread context; returns the new thread context."""
    await inputs.persist_suppressed_runtime_response(
        db=inputs.db,
        session_id=inputs.session_id,
        provider=inputs.runtime["provider_name"],
        model=inputs.usage_model,
        request_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        response=inputs.response,
        raw_output=messages_payload
        if not repeated
        else {**messages_payload, "suppressed_as_repeated_previous_step_summary": True},
        trace_limits=inputs.runtime_settings,
    )
    existing_thread_context = await inputs.persist_runtime_thread_context(
        db=inputs.db,
        session_id=inputs.session_id,
        message_id=inputs.assistant_msg.id,
        current_user_message=inputs.current_turn_content,
        assistant_content=content or reminder,
        context_snapshot=inputs.context_snapshot,
        tool_trace=[],
        raw_output=messages_payload
        if repeated
        else {**messages_payload, "suppressed_as_duplicate_no_tool_response": True},
    )
    await inputs.db.commit()
    return existing_thread_context


async def handle_repeated_no_tool_response(
    inputs: NoToolResponseInputs,
    *,
    content: str,
    no_tool_signature: str | None,
    no_tool_similarity: float,
    repeated: bool,
    repeated_count: int,
) -> dict[str, Any]:
    """A reply repeating the previous one (or the previous step's summary): recover or stop the turn."""
    duplicate_count = inputs.duplicate_no_tool_response_count + (0 if repeated else 1)
    recovery, reminder, messages_payload = _plan_repeat_recovery(
        inputs,
        content=content,
        no_tool_signature=no_tool_signature,
        no_tool_similarity=no_tool_similarity,
        duplicate_count=duplicate_count,
        repeated_count=repeated_count,
        repeated=repeated,
    )
    existing_thread_context = await _persist_repeat(
        inputs, content=content, reminder=reminder, messages_payload=messages_payload, repeated=repeated
    )
    final_content = str(recovery.get("final_content") or "")
    if not repeated and final_content:
        response = inputs.response
        await inputs.persist_traced_assistant_message(
            db=inputs.db,
            session_id=inputs.session_id,
            content=final_content,
            provider=inputs.runtime["provider_name"],
            model=inputs.usage_model,
            input_messages=inputs.request_messages,
            context_snapshot=inputs.context_snapshot,
            tool_trace=[],
            raw_output=messages_payload,
            usage=response.get("usage", {}),
            tokens_in=response.get("usage", {}).get("prompt_tokens", 0),
            tokens_out=response.get("usage", {}).get("completion_tokens", 0),
            trace_limits=inputs.runtime_settings,
        )
        return {
            "action": "return",
            "yield_content": final_content,
            "existing_thread_context": existing_thread_context,
            "duplicate_no_tool_response_count": duplicate_count,
            "repeated_previous_step_summary_count": repeated_count,
        }
    return {
        "action": "continue",
        "yield_content": content or reminder if repeated else None,
        "existing_thread_context": existing_thread_context,
        "duplicate_no_tool_response_count": duplicate_count,
        "repeated_previous_step_summary_count": repeated_count,
        "followup_system_message": reminder,
    }


__all__ = ["handle_repeated_no_tool_response"]
