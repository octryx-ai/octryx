"""Runtime-call failure path of a standard loop turn: research-context hold, salvage and the failed trace."""

from __future__ import annotations

from typing import Any

from app.services.content_security.refusal import with_turn_error_class
from app.services.prompt_catalog import render_prompt

from ...core.runtime.runtime_admission_contract import admission_refusal_of_attempts
from ...core.runtime.runtime_errors import RUNTIME_ERROR_CONTENT_POLICY_DENIED
from ...core.runtime.trace_runtime import compact_trace_value
from ...core.runtime.turn_execution_binding import bound_turn_started_at
from ...core.turn.runtime_recovery_telemetry import summarize_runtime_recovery
from ._loop_runtime_turn_inputs import RuntimeTurnInputs


def _runtime_unreachable_user_message(runtime_attempts: list[dict[str, Any]]) -> str | None:
    error_attempts = [attempt for attempt in runtime_attempts if attempt.get("status") == "error"]
    if not error_attempts:
        return None
    # Decided from the typed attempt facts (``admission_refusal_of_attempts``), never from a message.
    if admission_refusal_of_attempts(runtime_attempts) == RUNTIME_ERROR_CONTENT_POLICY_DENIED:
        return render_prompt("answer.content.refused")
    if all(attempt.get("error_class") in {"timeout", "unreachable"} for attempt in error_attempts):
        return render_prompt("answer.runtime.unreachable")
    return None


def apply_runtime_recovery_telemetry(
    inputs: RuntimeTurnInputs,
    runtime_attempts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    runtime_recovery = summarize_runtime_recovery(runtime_attempts)
    if not runtime_recovery:
        return None
    inputs.context_snapshot["runtime_recovery"] = compact_trace_value(
        runtime_recovery,
        trace_limits=inputs.runtime_settings,
    )
    return runtime_recovery


def is_research_context_error(exc: Exception) -> bool:
    from ...engine.pre_dispatch._research_evidence_context import ResearchEvidenceContextError

    return isinstance(exc, ResearchEvidenceContextError)


async def hold_research_context_failure(inputs: RuntimeTurnInputs, exc: Any) -> dict[str, Any]:
    from ..control._loop_terminal_phase import hold_research_context

    db, session_id = inputs.db, inputs.session_id
    await hold_research_context(db=db, session_id=session_id, request_analysis=inputs.request_analysis,
                                turn_tool_history=inputs.turn_tool_history, reason=exc.reason)
    await inputs.persist_traced_assistant_message(
        db=db, session_id=session_id, content=str(exc), provider="context-preflight", model="unresolved",
        input_messages=[], context_snapshot={"research_context_hold": exc.reason},
        raw_output={"error": exc.reason, "runtime_attempts": list(getattr(exc, "runtime_attempts", []) or [])},
        trace_limits=inputs.runtime_settings,
    )
    return {"action": "error", "event": inputs.event_factory(role="assistant", content=str(exc))}


async def finish_runtime_failure(
    inputs: RuntimeTurnInputs,
    exc: Exception,
    runtime_attempts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist the failed turn (salvaged from this turn's own evidence when possible) and end it."""
    db, session_id = inputs.db, inputs.session_id
    context_snapshot = inputs.context_snapshot
    runtime_settings = inputs.runtime_settings
    error_msg = _runtime_unreachable_user_message(runtime_attempts) or f"Agent error: {str(exc)}"
    runtime_recovery = apply_runtime_recovery_telemetry(inputs, runtime_attempts)
    if runtime_attempts:
        context_snapshot["runtime_attempts"] = compact_trace_value(runtime_attempts, trace_limits=runtime_settings)
    workflow_contract = inputs.workflow_contract_from_request_analysis(inputs.request_analysis)
    # A failed turn presents only what it produced itself: the salvage
    # reads rows persisted since this turn was admitted, never the history.
    turn_started_at = bound_turn_started_at(session_id)
    salvage_message = (
        await inputs._build_runtime_error_salvage_message(
            db=db,
            session_id=session_id,
            request_messages=inputs.request_messages,
            turn_started_at=turn_started_at,
        )
        if turn_started_at is not None
        else ""
    )
    artifact_contract_satisfied = inputs.workflow_artifact_contract_satisfied(
        workflow_contract,
        turn_tool_history=inputs.turn_tool_history,
    )
    if salvage_message:
        error_msg = salvage_message
    await inputs.persist_traced_assistant_message(
        db=db,
        session_id=session_id,
        content=error_msg,
        provider="runtime-fallback",
        model="unresolved",
        input_messages=inputs.request_messages,
        context_snapshot=context_snapshot,
        # A content-policy refusal is recorded as its closed class (typed provenance, never the text).
        raw_output=with_turn_error_class({
            "error": str(exc),
            "runtime_attempts": runtime_attempts,
            "runtime_recovery": runtime_recovery,
        }, exc),
        trace_limits=runtime_settings,
    )
    if salvage_message and artifact_contract_satisfied:
        return {"action": "return", "event": inputs.event_factory(role="assistant", content=error_msg)}
    return {"action": "error", "event": inputs.event_factory(role="assistant", content=error_msg)}
