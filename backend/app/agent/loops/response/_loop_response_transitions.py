"""Transition and placeholder response guards for the standard loop.

``handle_transition_response_guards`` checks the reply in a fixed order; stall guards that count, nudge and
eventually stop the turn live in ``_loop_response_transition_stalls``.
"""

from __future__ import annotations

import re
from typing import Any

from ._loop_pseudo_tool_calls import handle_pseudo_tool_call_reply
from ._loop_response_transition_inputs import TransitionGuardInputs, transition_loop_limit, transition_result
from ._loop_response_transition_stalls import (
    placeholder_response_guard,
    transitional_response_guard,
)

_STEP_PROGRESS_HEADING = re.compile(r"^\s*(?:---\s*)?(?:#+\s*)?step\s+\d+\s*/\s*\d+\s*:", re.IGNORECASE)


def _looks_like_sub_agent_resume_prompt(text: str) -> bool:
    lowered = str(text or "").lower()
    return "sub-agent" in lowered or "sub agent" in lowered or "subagents" in lowered


async def _pseudo_tool_call_outcome(run: TransitionGuardInputs) -> dict[str, Any] | None:
    # A reply that writes tool calls as text is never delivered as the answer.
    pseudo_outcome = await handle_pseudo_tool_call_reply(
        db=run.db, session_id=run.session_id, runtime=run.runtime, response=run.response,
        request_messages=run.request_messages, messages=run.messages, context_snapshot=run.context_snapshot,
        runtime_attempts=run.runtime_attempts, runtime_settings=run.runtime_settings, usage_model=run.usage_model,
        content=run.content, tool_calls=run.tool_calls, current_tool_definitions=run.current_tool_definitions,
        consecutive_non_progress_response_count=run.consecutive_non_progress_response_count,
        retry_limit=transition_loop_limit(run), persist_turn_trace=run.persist_turn_trace,
        persist_traced_assistant_message=run.persist_traced_assistant_message,
    )
    if pseudo_outcome is None:
        return None
    return {**pseudo_outcome, "consecutive_transitional_response_count": run.consecutive_transitional_response_count}


def _is_step_progress_reply(run: TransitionGuardInputs) -> bool:
    return bool(
        not run.tool_calls
        and run.current_step
        and (
            run.looks_like_step_completion_summary(run.content or "")
            or _STEP_PROGRESS_HEADING.search(run.content or "") is not None
        )
    )


def _is_placeholder_reply(run: TransitionGuardInputs) -> bool:
    content = run.content
    textual_tool_request_placeholder = str(content or "").lstrip().lower().startswith("tool request ")
    # A truncated textual tool call (e.g. a lone `<tool_call>` opener) is a
    # placeholder even when the turn carried zero native tool definitions: on
    # catalog-prompted runtimes the tool call happens inline-textually, so the
    # retry nudge must fire.
    truncated_textual_tool_call = "<tool_call>" in str(content or "").lower()
    # The latest user message decides whether a bare "OK" is the requested answer or a placeholder.
    return bool(
        run.is_non_substantive_assistant_response(content, run.tool_calls, user_message=run.latest_user_message)
        and (run.current_tool_definitions or textual_tool_request_placeholder or truncated_textual_tool_call)
    )


async def handle_transition_response_guards(run: TransitionGuardInputs) -> dict[str, Any]:
    """Guard a model reply against transitional or placeholder text; the counters in ``run`` are updated."""
    pseudo_outcome = await _pseudo_tool_call_outcome(run)
    if pseudo_outcome is not None:
        return pseudo_outcome

    if not run.tool_calls and str(run.content or "").strip() and _looks_like_sub_agent_resume_prompt(
        run.latest_user_message
    ):
        return transition_result(run, "none")

    if _is_step_progress_reply(run):
        run.consecutive_transitional_response_count = 0
        return transition_result(run, "none")

    if run.is_transitional_assistant_response(run.content, run.tool_calls, bool(run.current_tool_definitions)):
        return await transitional_response_guard(run)

    run.consecutive_transitional_response_count = 0
    if _is_placeholder_reply(run):
        return await placeholder_response_guard(run)
    return transition_result(run, "none")
