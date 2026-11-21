"""Stuck-loop and iteration-ceiling phases of ``handle_post_tool_outcome``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ....services.prompt_catalog import render_prompt
from ...core.runtime.trace_runtime import compact_trace_value
from ..control._loop_recovery import _apply_loop_recovery_to_context
from ._loop_post_tool_phases import _aws_evidence_report_outcome, _persist_stop_run_and_return, _PostToolEnv

_STEPLESS_STUCK_LOOP_KINDS = {
    "repeated_same_target_loop",
    "repetitive_knowledge_lookup_loop",
    "repetitive_evidence_target_cycle",
    "repetitive_tool_error_loop",
    "repetitive_tool_loop",
}
_STEP_STUCK_LOOP_KINDS = {
    "repetitive_tool_error_loop",
    "repetitive_empty_search_loop",
    "repetitive_knowledge_lookup_loop",
    "repetitive_evidence_target_cycle",
}


async def _dispatch_loop_recovery(
    env: _PostToolEnv,
    *,
    recovery: dict[str, Any],
    compact_event: Any,
    compact_recovery: Any,
    current_step: dict[str, Any],
    current_step_index: int,
    wrapup_iterations: int,
) -> dict[str, Any]:
    """Map a loop-recovery plan onto the loop action dicts (shared by the stuck-loop and iteration-ceiling phases)."""
    if recovery.get("action") == "move_to_next_step":
        return {
            "action": "advance_step",
            "system_message": str(recovery.get("system_message") or ""),
            "current_step_index": current_step_index + 1,
            "current_step_iterations": 0,
            "current_step_tool_activity": False,
            "current_step_wrapup_forced": False,
        }
    if recovery.get("action") == "stop_run":
        final_content = str(recovery.get("final_content") or "")
        return await _persist_stop_run_and_return(
            env,
            final_content=final_content,
            raw_output={
                "content": env.content,
                "tool_calls": [],
                "runtime_attempts": env.runtime_attempts,
                "stalled_after_tool_loop": True,
                "step_name": current_step.get("name"),
                "stuck_loop_detector": compact_event,
                "loop_recovery": compact_recovery,
            },
        )
    return {
        "action": "append_system_message",
        "system_message": str(recovery.get("system_message") or ""),
        "current_step_iterations": wrapup_iterations,
        "current_step_wrapup_forced": True,
    }


async def _stepless_stuck_loop_outcome(env: _PostToolEnv, *, stuck_loop_kind: str) -> dict[str, Any]:
    if stuck_loop_kind in {"repetitive_tool_error_loop", "repetitive_tool_loop"}:
        aws_stuck_outcome = await _aws_evidence_report_outcome(env, source="aws_diagnosis_stuck_evidence_report")
        if aws_stuck_outcome:
            return aws_stuck_outcome
    return {
        "action": "append_system_message",
        "system_message": render_prompt("guard.stuck_loop.final_answer"),
    }


async def _stuck_loop_outcome(
    env: _PostToolEnv,
    *,
    stuck_loop_event: dict[str, Any] | None,
    current_step: dict[str, Any] | None,
    current_step_index: int,
    active_steps: list[dict[str, Any]],
    current_step_wrapup_forced: bool,
    plan_loop_recovery: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    stuck_loop_kind = str((stuck_loop_event or {}).get("kind") or "").strip().lower()
    if not current_step and stuck_loop_kind in _STEPLESS_STUCK_LOOP_KINDS:
        return await _stepless_stuck_loop_outcome(env, stuck_loop_kind=stuck_loop_kind)
    if not (current_step and stuck_loop_kind in _STEP_STUCK_LOOP_KINDS):
        return None
    compact_stuck_loop_event = env.context_snapshot.get("stuck_loop_detector")
    recovery = plan_loop_recovery(
        event=stuck_loop_event,
        step=current_step,
        has_followup_steps=bool(current_step_index < len(active_steps) - 1),
        wrapup_forced=current_step_wrapup_forced,
    )
    compact_recovery = _apply_loop_recovery_to_context(
        context_snapshot=env.context_snapshot,
        recovery=recovery,
        runtime_settings=env.runtime_settings,
    )
    return await _dispatch_loop_recovery(
        env,
        recovery=recovery,
        compact_event=compact_stuck_loop_event,
        compact_recovery=compact_recovery,
        current_step=current_step,
        current_step_index=current_step_index,
        wrapup_iterations=0,
    )


async def _iteration_ceiling_outcome(
    env: _PostToolEnv,
    *,
    current_step: dict[str, Any] | None,
    current_step_index: int,
    active_steps: list[dict[str, Any]],
    current_step_iterations: int,
    current_step_max_iterations: int,
    current_step_wrapup_forced: bool,
    build_iteration_ceiling_event: Callable[..., dict[str, Any]],
    plan_loop_recovery: Callable[..., dict[str, Any]],
) -> dict[str, Any] | None:
    if not (current_step and current_step_iterations >= current_step_max_iterations):
        return None
    iteration_ceiling_event = build_iteration_ceiling_event(
        step=current_step,
        step_index=current_step_index,
        attempts_used=current_step_iterations,
        max_iterations=current_step_max_iterations,
    )
    compact_iteration_ceiling_event = compact_trace_value(iteration_ceiling_event, trace_limits=env.runtime_settings)
    env.context_snapshot["stuck_loop_detector"] = compact_iteration_ceiling_event
    recovery = plan_loop_recovery(
        event=iteration_ceiling_event,
        step=current_step,
        has_followup_steps=bool(current_step_index < len(active_steps) - 1),
        wrapup_forced=current_step_wrapup_forced,
    )
    compact_recovery = _apply_loop_recovery_to_context(
        context_snapshot=env.context_snapshot,
        recovery=recovery,
        runtime_settings=env.runtime_settings,
    )
    return await _dispatch_loop_recovery(
        env,
        recovery=recovery,
        compact_event=compact_iteration_ceiling_event,
        compact_recovery=compact_recovery,
        current_step=current_step,
        current_step_index=current_step_index,
        wrapup_iterations=current_step_max_iterations,
    )
