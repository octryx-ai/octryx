"""Stall guards of ``handle_transition_response_guards``: transitional and placeholder replies, with the
knowledge-evidence salvage that answers instead of a stop message where possible."""

from __future__ import annotations

from typing import Any

from ....services.knowledge_salvage import build_knowledge_salvage_answer
from ....services.prompt_catalog import render_prompt
from ....services.turn_tool_history import _latest_successful_tool_result
from ...core.guards.stop_text import agent_stop_text
from ._loop_response_transition_inputs import (
    TransitionGuardInputs,
    persist_stop_message,
    persist_suppressed_trace,
    transition_loop_limit,
    transition_result,
)


def _knowledge_fallback_answer(*, user_message: str, turn_tool_history: list[dict[str, Any]]) -> str:
    salvage = build_knowledge_salvage_answer(user_message, turn_tool_history, max_items=10, content_chars=420)
    if salvage:
        return salvage

    # The governed search found nothing: that is the answer. There is no handover to another store.
    search = _latest_successful_tool_result(turn_tool_history, "knowledge_search")
    if search.get("state") == "ok" and not search.get("result_count"):
        return render_prompt("answer.knowledge.nothing_documented")
    return ""


async def _transitional_stop(run: TransitionGuardInputs) -> dict[str, Any]:
    raw_base = {"content": run.content, "tool_calls": [], "runtime_attempts": run.runtime_attempts}
    final_content = (
        run.build_stalled_step_message(run.current_step)
        if run.current_step
        else agent_stop_text("loop.transition.transition_stop")
    )
    await persist_stop_message(
        run,
        final_content=final_content,
        raw_output={
            **raw_base,
            "stalled_on_transitional_loop": True,
            "transition_loop_count": run.consecutive_transitional_response_count,
        },
    )
    await run.db.commit()
    return transition_result(run, "return", yield_content=final_content, yield_model=run.usage_model)


async def transitional_response_guard(run: TransitionGuardInputs) -> dict[str, Any]:
    run.consecutive_transitional_response_count += 1
    run.consecutive_non_progress_response_count += 1
    reminder = render_prompt("loop.transition.transition_reminder")
    run.messages.append({"role": "assistant", "content": run.content})
    run.messages.append({"role": "system", "content": reminder})
    await persist_suppressed_trace(
        run,
        raw_output={
            "content": run.content,
            "tool_calls": [],
            "runtime_attempts": run.runtime_attempts,
            "suppressed_as_transitional": True,
        },
    )
    if run.consecutive_non_progress_response_count >= transition_loop_limit(run):
        return await _transitional_stop(run)
    await run.db.commit()
    return transition_result(run, "continue")


async def _placeholder_stop(run: TransitionGuardInputs) -> dict[str, Any]:
    knowledge_fallback = _knowledge_fallback_answer(
        user_message=run.latest_user_message, turn_tool_history=run.turn_tool_history
    )
    final_content = knowledge_fallback or (
        run.build_stalled_step_message(run.current_step)
        if run.current_step
        else agent_stop_text("loop.transition.placeholder_stop")
    )
    await persist_stop_message(
        run,
        final_content=final_content,
        raw_output={
            "content": run.content,
            "tool_calls": run.tool_calls or [],
            "runtime_attempts": run.runtime_attempts,
            "stalled_on_non_substantive_loop": True,
            "non_progress_loop_count": run.consecutive_non_progress_response_count,
            "salvaged_from_knowledge_history": bool(run.workflow_id == "knowledge_request" and knowledge_fallback),
        },
    )
    await run.db.commit()
    return transition_result(run, "return", yield_content=final_content, yield_model=run.usage_model)


async def placeholder_response_guard(run: TransitionGuardInputs) -> dict[str, Any]:
    run.consecutive_non_progress_response_count += 1
    reminder = render_prompt("loop.transition.placeholder_reminder")
    run.messages.append({"role": "assistant", "content": run.content or ""})
    run.messages.append({"role": "system", "content": reminder})
    await persist_suppressed_trace(
        run,
        raw_output={
            "content": run.content,
            "tool_calls": run.tool_calls or [],
            "runtime_attempts": run.runtime_attempts,
            "suppressed_as_non_substantive": True,
        },
    )
    if run.consecutive_non_progress_response_count >= transition_loop_limit(run):
        return await _placeholder_stop(run)
    await run.db.commit()
    return transition_result(run, "continue")
