"""Coding guard inputs and the suppress-then-stop nudges for coding replies without progress."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....services.prompt_catalog import render_prompt
from ...core.guards.stop_text import agent_stop_text
from ._loop_message_dedupe import append_unique_assistant_context, append_unique_system_message


@dataclass(kw_only=True)
class CodingGuardInputs:
    """Inputs of ``handle_coding_response_guards`` (same names and defaults as its callers pass)."""

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
    current_step: dict[str, Any] | None
    current_step_index: int
    current_step_iterations: int
    current_step_max_iterations: int
    current_step_tool_activity: bool
    active_steps: list[dict[str, Any]]
    workflow_artifact_ready_for_final_response: bool
    current_turn_content: str
    capability_type: str
    tool_context: Any
    turn_tool_history: list[dict[str, Any]]
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    consecutive_coding_no_execution_count: int
    allows_noop_step_completion: Callable[[dict[str, Any] | None, str], bool]
    build_required_tool_reminder: Callable[[dict[str, Any]], str]
    build_stalled_step_message: Callable[[dict[str, Any]], str]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_turn_trace: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    _has_meaningful_coding_execution: Callable[[list[dict[str, Any]]], bool]
    _is_probable_coding_change_request: Callable[..., bool]
    _looks_like_coding_intent_only_response: Callable[[str], bool]
    phase_tool_evidence_present: bool = False
    # The explicit governed signal: the turn's workflow contract carries the approved verification contract.
    governed_coding: bool = False


@dataclass(frozen=True)
class CodingNudge:
    """One coding guard's reminder, its trace flags and its stop text once the retry budget is spent."""

    reminder_key: str
    suppressed_flag: str
    stalled_flag: str
    stop_key: str


NO_EXECUTION_NUDGE = CodingNudge(
    "loop.coding.inspection_not_enough",
    "suppressed_for_coding_no_execution",
    "stalled_on_coding_no_execution",
    "loop.coding.no_evidence_stop",
)
GOVERNED_WITHOUT_DELIVERY_NUDGE = CodingNudge(
    "loop.coding.analysis_only",
    "suppressed_for_governed_coding_without_delivery",
    "stalled_on_governed_coding_without_delivery",
    "loop.coding.analysis_only_stop",
)
INTENT_ONLY_NUDGE = CodingNudge(
    "loop.coding.narration",
    "suppressed_for_coding_intent_only",
    "stalled_on_coding_intent_only",
    "loop.coding.narration_stop",
)


def guard_counts(inputs: CodingGuardInputs) -> dict[str, int]:
    return {
        "consecutive_non_progress_response_count": inputs.consecutive_non_progress_response_count,
        "consecutive_coding_no_execution_count": inputs.consecutive_coding_no_execution_count,
        "consecutive_transitional_response_count": inputs.consecutive_transitional_response_count,
    }


async def nudge_coding_reply(
    inputs: CodingGuardInputs, nudge: CodingNudge, prior_turn_tool_names: list[str]
) -> dict[str, Any]:
    """Suppress the reply with a reminder; stop the turn once the non-progress budget is spent."""
    inputs.consecutive_coding_no_execution_count += 1
    inputs.consecutive_non_progress_response_count += 1
    content = inputs.content
    append_unique_assistant_context(inputs.messages, content or "")
    append_unique_system_message(inputs.messages, render_prompt(nudge.reminder_key))
    trace_fields = {
        "content": content,
        "tool_calls": [],
        "runtime_attempts": inputs.runtime_attempts,
    }
    tail = {
        "coding_no_execution_count": inputs.consecutive_coding_no_execution_count,
        "prior_turn_tool_names": prior_turn_tool_names,
    }
    await inputs.persist_suppressed_runtime_response(
        db=inputs.db,
        session_id=inputs.session_id,
        provider=inputs.runtime["provider_name"],
        model=inputs.usage_model,
        request_messages=inputs.request_messages,
        context_snapshot=inputs.context_snapshot,
        response=inputs.response,
        raw_output={**trace_fields, nudge.suppressed_flag: True, **tail},
        trace_limits=inputs.runtime_settings,
    )
    limit = max(2, int(inputs.runtime_settings.get("stuck_loop_no_tool_duplicate_threshold") or 2))
    if inputs.consecutive_non_progress_response_count >= limit:
        return await _stop_coding_turn(inputs, nudge, {**trace_fields, nudge.stalled_flag: True, **tail})
    await inputs.db.commit()
    return {"action": "continue", **guard_counts(inputs)}


async def _stop_coding_turn(
    inputs: CodingGuardInputs, nudge: CodingNudge, raw_output: dict[str, Any]
) -> dict[str, Any]:
    final_content = agent_stop_text(nudge.stop_key)
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
        raw_output=raw_output,
        usage=response.get("usage", {}),
        tokens_in=response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=response.get("usage", {}).get("completion_tokens", 0),
        trace_limits=inputs.runtime_settings,
    )
    await inputs.db.commit()
    return {
        "action": "return", "yield_content": final_content, "yield_model": inputs.usage_model, **guard_counts(inputs)
    }
