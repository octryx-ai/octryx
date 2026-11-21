"""Loop recovery and trace helpers for the standard agent loop."""

from __future__ import annotations

from typing import Any

from app.services.request_analysis import required_summary_tools_from_request_analysis

from ...core.runtime.trace_runtime import compact_trace_value


def _apply_stuck_loop_event_to_trace(
    *,
    context_snapshot: dict[str, Any],
    turn_trace: Any | None,
    event: dict[str, Any] | None,
    runtime_settings: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(event, dict) or not event:
        return None
    compact_event = compact_trace_value(event, trace_limits=runtime_settings)
    context_snapshot["stuck_loop_detector"] = compact_event
    if turn_trace is not None:
        raw_output = dict(turn_trace.raw_output or {}) if isinstance(turn_trace.raw_output, dict) else {}
        raw_output["stuck_loop_detector"] = compact_event
        turn_trace.raw_output = compact_trace_value(raw_output, trace_limits=runtime_settings)
    return compact_event


def _apply_loop_recovery_to_context(
    *,
    context_snapshot: dict[str, Any],
    recovery: dict[str, Any] | None,
    runtime_settings: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(recovery, dict) or not recovery:
        return None
    compact_recovery = compact_trace_value(recovery, trace_limits=runtime_settings)
    context_snapshot["loop_recovery"] = compact_recovery
    return compact_recovery


def _augment_step_allowed_tools_for_request_analysis(
    step_allowed_tools: set[str],
    request_analysis: dict[str, Any] | None,
) -> set[str]:
    augmented = set(step_allowed_tools)
    augmented.update(required_summary_tools_from_request_analysis(request_analysis))
    return augmented


__all__ = [
    "_apply_stuck_loop_event_to_trace",
    "_apply_loop_recovery_to_context",
    "_augment_step_allowed_tools_for_request_analysis",
]
