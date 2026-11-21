"""The child turn of a workflow ``agent_step``: running it, reading its outcome, ending its session."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session, TurnTrace
from ...time_utils import utc_now
from ..agent_definition_execution_outcomes import payload_resolution_metadata
from ..flow_runtime_governance import (
    FlowRuntimeLimits,
    FlowRuntimeUsage,
    ensure_run_duration_within_limits,
)
from ..session.run_state import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_STOPPED,
    get_session_run_status,
    set_session_run_state,
)

SUCCESS_STATES = frozenset({"finished_unverified", "completed"})

# Turn summary state -> (closed code, failure category, required action).
_OUTCOMES: dict[str, tuple[str, str, str]] = {
    "denied": ("agent_turn_denied", "policy_blocked", "review_policy"),
    "blocked_unknown": ("agent_turn_denied", "policy_blocked", "review_policy"),
    "needs_configuration": ("agent_turn_needs_configuration", "input_contract_error", "fix_workflow_configuration"),
    "needs_clarification": ("agent_turn_needs_clarification", "human_review_required", "human_review"),
    "needs_approval": ("agent_turn_needs_approval", "human_review_required", "human_review"),
    "needs_confirmation": ("agent_turn_needs_approval", "human_review_required", "human_review"),
    "waiting_approval": ("agent_turn_needs_approval", "human_review_required", "human_review"),
    "stopped": ("agent_turn_stopped", "runtime_exception", "inspect_trace"),
    "failed": ("agent_turn_failed", "runtime_exception", "inspect_trace"),
    "cancelled": ("agent_turn_cancelled", "runtime_exception", "inspect_trace"),
}
_UNKNOWN_OUTCOME = ("agent_turn_outcome_unknown", "runtime_exception", "inspect_trace")


async def _finish_child(db: AsyncSession, child: Session, *, succeeded: bool, reason: str) -> None:
    """Give the one-turn child session its terminal state, like finished sub-agent children."""
    child.status = "completed" if succeeded else "error"
    child.ended_at = utc_now()
    metadata = dict(child.metadata_ or {})
    metadata.pop("current_turn_user_message_id", None)
    metadata["flow_agent_step_outcome"] = reason
    child.metadata_ = metadata
    terminal = {RUN_STATUS_COMPLETED, RUN_STATUS_FAILED, RUN_STATUS_STOPPED}
    if not succeeded:
        set_session_run_state(child, RUN_STATUS_FAILED, reason)
    elif get_session_run_status(child) not in terminal:
        set_session_run_state(child, RUN_STATUS_COMPLETED, reason)
    await db.flush()


async def _run_agent_turn(
    *,
    db: AsyncSession,
    session: Session,
    task: str,
    payload: dict[str, Any] | None,
    user_id: str,
    agent_type: str,
    parent_session_id: str | None,
) -> str:
    from ...agent.engine import run_agent
    from ...models.runtime.product_run import RUN_ORIGIN_SUB_AGENT

    final = ""
    async for event in run_agent(
        session_id=session.id,
        user_message=task,
        user_id=user_id,
        project_id=session.project_id,
        agent_type=agent_type,
        db=db,
        runtime_target_id=str((payload or {}).get("runtimeTargetId") or "") or None,
        thinking_level=str((payload or {}).get("thinkingLevel") or "") or None,
        agent_definition=payload,
        parent_session_id=parent_session_id,
        sub_agent_depth=1,
        run_origin=RUN_ORIGIN_SUB_AGENT,
    ):
        if getattr(event, "role", "") == "assistant" and getattr(event, "content", ""):
            final = str(event.content)
    return final


async def _reload_expired(db: AsyncSession) -> None:
    """Reload objects a rolled-back turn expired, so the flow run can record the node's outcome."""
    for instance in list(db.identity_map.values()):
        state = inspect(instance)
        if state.expired and state.persistent:
            await db.refresh(instance)


def _remaining_seconds(limits: FlowRuntimeLimits | None, usage: FlowRuntimeUsage | None) -> float | None:
    """Seconds left of the flow run's ``max_run_seconds``; ``None`` when no limit is configured."""
    if limits is None or usage is None or limits.max_run_seconds is None:
        return None
    ensure_run_duration_within_limits(usage=usage, limits=limits)
    return max(0.0, limits.max_run_seconds - (utc_now() - usage.started_at).total_seconds())


async def _turn_state(db: AsyncSession, session_id: str) -> tuple[dict[str, Any], TurnTrace | None]:
    """The child turn's ``turn_execution_summary.v1`` and its final trace."""
    from ..session.turn_execution_summary import build_turn_execution_summary
    from ..session.turn_execution_summary_service import load_turn_execution_evidence

    trace = (
        await db.execute(
            select(TurnTrace)
            .where(TurnTrace.session_id == session_id)
            .order_by(TurnTrace.created_at.desc(), TurnTrace.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if trace is None:
        return {"state": "unknown"}, None
    return build_turn_execution_summary(await load_turn_execution_evidence(db, trace)), trace


def _turn_facts(summary: dict[str, Any], trace: TurnTrace | None) -> dict[str, Any]:
    """Execution evidence of the child turn. ``finished_unverified`` means the turn finished, not that
    its result was verified."""
    usage = dict(trace.usage_json or {}) if trace is not None and isinstance(trace.usage_json, dict) else {}
    return {
        "state": str(summary.get("state") or "unknown"),
        "trace_id": trace.id if trace is not None else None,
        "provider": (trace.provider or None) if trace is not None else None,
        "model": (trace.model or None) if trace is not None else None,
        "tokens_in": usage.get("prompt_tokens"),
        "tokens_out": usage.get("completion_tokens"),
    }


def _provenance(agent_id: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"definition_id": None, "source": "no_agent_definition"}
    resolution = payload_resolution_metadata(payload)
    facts = next(iter(resolution.values()), {}) if resolution else {}
    return {
        "definition_id": agent_id,
        "name": str(payload.get("name") or ""),
        "mode": facts.get("mode") or None,
        "source": facts.get("source") or None,
        "revision_number": facts.get("revision_number"),
    }


def _checked_reply_data(summary: dict[str, Any], final_text: str) -> dict[str, Any] | None:
    """The parsed reply object when the turn's checked JSON reply was satisfied, else ``None``.

    The summary's ``reply_contract`` record is the check of exactly this turn's final reply, read only
    where it agrees with the finished trace. Free text is never coerced: without a satisfied record, or if the
    text does not parse to an object, there is no ``data``.
    """
    record = summary.get("reply_contract") if isinstance(summary, dict) else None
    if not isinstance(record, dict) or record.get("status") != "satisfied":
        return None
    try:
        value = json.loads(final_text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None
