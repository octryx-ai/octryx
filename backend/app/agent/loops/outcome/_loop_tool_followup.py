"""Tool-result follow-up orchestration for the standard agent loop.

``handle_tool_followup`` records the tool round, then runs the follow-up phases in a fixed order; the first phase
that returns an action dict decides the loop action. Phases live in ``_loop_tool_followup_guards`` and
``_loop_tool_followup_planning``.
"""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt
from ...core.guards.summary_domains import missing_summary_domains
from ...core.runtime.trace_runtime import compact_trace_value
from ...core.turn.decision_timeline import append_tool_execution_event
from ._loop_tool_followup_guards import (
    final_step_ceiling_outcome,
    incomplete_evidence_outcome,
    tdd_cycle_outcome,
    waiting_result_outcome,
)
from ._loop_tool_followup_inputs import ToolFollowupInputs
from ._loop_tool_followup_planning import (
    forced_tool_calls_outcome,
    post_tool_followup_result,
    refresh_workflow_contract,
)

_FOLLOWUP_PHASES = (
    final_step_ceiling_outcome,
    waiting_result_outcome,
    incomplete_evidence_outcome,
    refresh_workflow_contract,
    forced_tool_calls_outcome,
    tdd_cycle_outcome,
)


async def _record_tool_trace(run: ToolFollowupInputs) -> None:
    run.turn_trace.tool_trace_json = compact_trace_value(
        [
            {
                "tool_name": item.get("tool_name"),
                "tool_call_id": item.get("tool_call_id"),
                "result": item.get("compact_result", item.get("result")),
            }
            for item in run.tool_results
        ],
        trace_limits=run.runtime_settings,
    )
    append_tool_execution_event(run.context_snapshot, tool_results=run.tool_results)
    run.stuck_loop_event = run.detect_tool_stuck_loop(
        step=run.current_step,
        history=run.step_tool_history,
        step_index=run.current_step_index,
        runtime_settings=run.runtime_settings,
    )
    compact_stuck_loop_event = run._apply_stuck_loop_event_to_trace(
        context_snapshot=run.context_snapshot,
        turn_trace=run.turn_trace,
        event=run.stuck_loop_event,
        runtime_settings=run.runtime_settings,
    )
    run.existing_thread_context = await run.persist_runtime_thread_context(
        db=run.db,
        session_id=run.session_id,
        message_id=run.assistant_msg.id,
        current_user_message=run.current_turn_content,
        assistant_content=str(run.persisted_assistant_content or ""),
        context_snapshot=run.context_snapshot,
        tool_trace=run.tool_results,
        raw_output={
            "content": run.persisted_assistant_content,
            "tool_calls": run.tool_calls or [],
            "stuck_loop_detector": compact_stuck_loop_event,
        },
    )
    await run.db.commit()


def _recent_tool_names(step_tool_history: list[dict[str, Any]], count: int) -> list[str]:
    return [
        str(item.get("tool_name") or "").strip()
        for item in step_tool_history[-count:]
        if str(item.get("tool_name") or "").strip()
    ]


def _nudge_artifact_loop(run: ToolFollowupInputs) -> None:
    recent_tool_names = _recent_tool_names(run.step_tool_history, 3)
    # Broader loop detection: check last 6 entries for repeated artifact loading
    recent_six_names = _recent_tool_names(run.step_tool_history, 6)
    artifact_loop_forced = len(recent_six_names) >= 6 and set(recent_six_names) == {"load_tool_artifact"}
    if artifact_loop_forced or (
        recent_tool_names
        and len(recent_tool_names) == 3
        and set(recent_tool_names) == {"load_tool_artifact"}
        and not missing_summary_domains(run.required_domains, run.covered_summary_domains)
    ):
        run.messages.append({"role": "system", "content": render_prompt("guard.artifact_loop.final_answer")})


async def handle_tool_followup(run: ToolFollowupInputs) -> dict[str, Any]:
    """Resolve the loop action after tool results arrive; ``run`` is updated while the follow-up runs."""
    await _record_tool_trace(run)
    run.current_step_iterations += 1
    run.current_step_tool_activity = True
    _nudge_artifact_loop(run)
    run.repeated_previous_step_summary_count = 0
    run.tool_event = run.event_factory(role="tool", tool_calls=run.tool_calls, tool_results=run.tool_results)
    for phase in _FOLLOWUP_PHASES:
        outcome = await phase(run)
        if outcome is not None:
            return outcome
    return await post_tool_followup_result(run)
