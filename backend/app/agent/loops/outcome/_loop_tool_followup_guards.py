"""Stop and wait phases of ``handle_tool_followup``: final-step ceiling, pending results, evidence, TDD cycle."""

from __future__ import annotations

from typing import Any

from ...core.guards.tdd_cycle import (
    advance_tdd_cycle_phase,
    build_tdd_cycle_progress_message,
    is_tdd_cycle_complete,
    is_tdd_cycle_step,
)
from ...core.runtime.trace_runtime import compact_trace_value
from ...core.turn.decision_timeline import append_quality_event
from ._loop_evidence_contracts import (
    build_incomplete_evidence_contract_reminder,
    critical_incomplete_evidence_contracts,
)
from ._loop_tool_followup_inputs import ToolFollowupInputs, followup_result, sync_turn_trace_context


def _ceiling_metadata(run: ToolFollowupInputs) -> dict[str, Any]:
    return {
        "step_index": run.current_step_index,
        "attempts_used": run.current_step_iterations,
        "max_iterations": run.current_step_max_iterations,
    }


async def _final_step_ceiling_stop(
    run: ToolFollowupInputs, *, recovery: dict[str, Any], compact_event: Any, compact_recovery: Any
) -> dict[str, Any]:
    final_content = str(recovery.get("final_content") or "")
    append_quality_event(
        run.context_snapshot,
        title="Final step iteration ceiling reached",
        status="blocked",
        detail="The final step continued calling tools after wrap-up was forced.",
        metadata=_ceiling_metadata(run),
    )
    sync_turn_trace_context(run)
    await run.persist_traced_assistant_message(
        db=run.db,
        session_id=run.session_id,
        content=final_content,
        provider=run.runtime["provider_name"],
        model=run.usage_model,
        input_messages=run.request_messages,
        context_snapshot=run.context_snapshot,
        tool_trace=run.tool_results,
        raw_output={
            "content": run.content,
            "tool_calls": [],
            "runtime_attempts": run.runtime_attempts,
            "stalled_after_tool_loop": True,
            "step_name": run.current_step.get("name"),
            "stuck_loop_detector": compact_event,
            "loop_recovery": compact_recovery,
        },
        usage=run.response.get("usage", {}),
        tokens_in=run.response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=run.response.get("usage", {}).get("completion_tokens", 0),
        trace_limits=run.runtime_settings,
    )
    return followup_result(
        run,
        "return",
        yield_content=final_content,
        yield_model=run.usage_model,
        current_step_wrapup_forced=run.current_step_wrapup_forced,
    )


async def final_step_ceiling_outcome(run: ToolFollowupInputs) -> dict[str, Any] | None:
    if not (
        run.current_step
        and run.current_step_iterations >= run.current_step_max_iterations
        and run.current_step_index >= len(run.active_steps) - 1
    ):
        return None
    iteration_ceiling_event = run.build_iteration_ceiling_event(
        step=run.current_step,
        step_index=run.current_step_index,
        attempts_used=run.current_step_iterations,
        max_iterations=run.current_step_max_iterations,
    )
    compact_event = compact_trace_value(iteration_ceiling_event, trace_limits=run.runtime_settings)
    run.context_snapshot["stuck_loop_detector"] = compact_event
    recovery = run.plan_loop_recovery(
        event=iteration_ceiling_event,
        step=run.current_step,
        has_followup_steps=False,
        wrapup_forced=run.current_step_wrapup_forced,
    )
    compact_recovery = compact_trace_value(recovery, trace_limits=run.runtime_settings)
    run.context_snapshot["loop_recovery"] = compact_recovery
    if recovery.get("action") == "stop_run":
        return await _final_step_ceiling_stop(
            run, recovery=recovery, compact_event=compact_event, compact_recovery=compact_recovery
        )
    append_quality_event(
        run.context_snapshot,
        title="Final step wrap-up forced",
        status="warning",
        detail="The final step reached its tool iteration ceiling and must conclude from gathered evidence.",
        metadata=_ceiling_metadata(run),
    )
    sync_turn_trace_context(run)
    return followup_result(
        run,
        "append_system_message",
        system_message=str(recovery.get("system_message") or ""),
        current_step_iterations=run.current_step_max_iterations,
        current_step_wrapup_forced=True,
    )


async def waiting_result_outcome(run: ToolFollowupInputs) -> dict[str, Any] | None:
    if not (
        run.has_pending_approval_result(run.tool_results)
        or run._has_awaiting_subagent_result(run.tool_results)
        or run._has_pending_clarification_result(run.tool_results)
    ):
        return None
    append_quality_event(
        run.context_snapshot,
        title="Tool execution is waiting",
        status="pending",
        detail="A tool result requires approval, clarification, or sub-agent completion.",
    )
    sync_turn_trace_context(run)
    return followup_result(run, "return")


async def incomplete_evidence_outcome(run: ToolFollowupInputs) -> dict[str, Any] | None:
    incomplete_contracts = critical_incomplete_evidence_contracts(run.tool_results)
    if not incomplete_contracts:
        return None
    append_quality_event(
        run.context_snapshot,
        title="Evidence contract incomplete",
        status="warning",
        detail="A workflow-critical tool result was compacted without all required evidence fields.",
        metadata={"contracts": incomplete_contracts},
    )
    run.messages.append(
        {"role": "system", "content": build_incomplete_evidence_contract_reminder(incomplete_contracts)}
    )
    sync_turn_trace_context(run)
    return followup_result(run, "continue")


async def tdd_cycle_outcome(run: ToolFollowupInputs) -> dict[str, Any] | None:
    if not (run.current_step and is_tdd_cycle_step(run.current_step) and run.tdd_cycle_state is not None):
        return None
    if advance_tdd_cycle_phase(run.tdd_cycle_state):
        run.messages.append({"role": "system", "content": build_tdd_cycle_progress_message(run.tdd_cycle_state)})
        await run.db.commit()
        return followup_result(run, "continue")
    if is_tdd_cycle_complete(run.tdd_cycle_state):
        run.messages.append({"role": "system", "content": build_tdd_cycle_progress_message(run.tdd_cycle_state)})
    return None
