"""Workflow ROI helpers for thread usage statistics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Session as AgentSession
from .workflow_roi_metrics import SessionUsageMetrics, _load_metrics_by_session_id, _load_quality_summary

BASELINE_SESSION_LIMIT = 20
BASELINE_SCAN_LIMIT = 250


@dataclass(frozen=True)
class WorkflowIdentity:
    workflow_id: str
    workflow_class: str
    project_id: str | None

    @property
    def has_identity(self) -> bool:
        return bool(self.workflow_id or self.workflow_class)


def workflow_identity_from_session(session: AgentSession | None) -> WorkflowIdentity:
    metadata = session.metadata_ if session and isinstance(session.metadata_, dict) else {}
    contract = metadata.get("workflow_contract") if isinstance(metadata.get("workflow_contract"), dict) else {}
    routing = metadata.get("workflow_routing") if isinstance(metadata.get("workflow_routing"), dict) else {}
    resolution = (
        metadata.get("workflow_routing_policy_resolution")
        if isinstance(metadata.get("workflow_routing_policy_resolution"), dict)
        else {}
    )
    return WorkflowIdentity(
        workflow_id=_first_text(
            contract.get("workflow_id"),
            metadata.get("expected_workflow_id"),
            routing.get("workflow_id"),
            resolution.get("workflow_id"),
        ),
        workflow_class=_first_text(
            contract.get("workflow_class"),
            metadata.get("workflow_class"),
            routing.get("workflow_class"),
            resolution.get("workflow_class"),
        ),
        project_id=session.project_id if session else None,
    )


async def build_workflow_roi_stats(
    db: AsyncSession,
    *,
    session_ids: list[str],
    current_metrics: dict[str, Any],
) -> dict[str, Any] | None:
    if not session_ids:
        return None

    current_sessions = (
        (
            await db.execute(
                select(AgentSession)
                .where(AgentSession.id.in_(session_ids))
                .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
            )
        )
        .scalars()
        .all()
    )
    current_identity = next(
        (identity for session in current_sessions if (identity := workflow_identity_from_session(session)).has_identity),
        None,
    )
    if current_identity is None:
        return None

    current = SessionUsageMetrics(
        input_tokens=int(current_metrics.get("input_tokens") or 0),
        output_tokens=int(current_metrics.get("output_tokens") or 0),
        total_cost=float(current_metrics.get("total_cost") or 0),
        llm_request_count=int(current_metrics.get("llm_request_count") or current_metrics.get("request_count") or 0),
        tool_call_count=int(current_metrics.get("tool_call_count") or 0),
        turn_trace_count=int(current_metrics.get("turn_trace_count") or 0),
    )
    baseline_sessions = await _load_baseline_sessions(
        db,
        identity=current_identity,
        excluded_session_ids={str(session_id) for session_id in session_ids},
    )
    baseline_metrics = await _load_metrics_by_session_id(db, [session.id for session in baseline_sessions])
    baseline_values = [baseline_metrics.get(session.id, SessionUsageMetrics()) for session in baseline_sessions]
    gate_quality = await _load_quality_summary(
        db,
        current_session_ids=session_ids,
        baseline_session_ids=[session.id for session in baseline_sessions],
    )
    return _serialize_roi(
        identity=current_identity,
        current=current,
        baseline_values=baseline_values,
        quality=gate_quality,
    )


def _serialize_roi(
    *,
    identity: WorkflowIdentity,
    current: SessionUsageMetrics,
    baseline_values: list[SessionUsageMetrics],
    quality: dict[str, Any],
) -> dict[str, Any]:
    baseline = _average_metrics(baseline_values)
    status = "baseline_available" if baseline_values else "insufficient_baseline"
    return {
        "status": status,
        "workflow_id": identity.workflow_id,
        "workflow_class": identity.workflow_class,
        "baseline_sample_count": len(baseline_values),
        "current": _serialize_metrics(current),
        "baseline": _serialize_metrics(baseline),
        "savings": {
            "token_delta": baseline.total_tokens - current.total_tokens,
            "token_reduction_percent": _reduction_percent(baseline.total_tokens, current.total_tokens),
            "cost_delta": baseline.total_cost - current.total_cost,
            "cost_reduction_percent": _reduction_percent(baseline.total_cost, current.total_cost),
            "llm_request_delta": baseline.llm_request_count - current.llm_request_count,
            "tool_call_delta": baseline.tool_call_count - current.tool_call_count,
        },
        "quality": quality,
    }


async def _load_baseline_sessions(
    db: AsyncSession,
    *,
    identity: WorkflowIdentity,
    excluded_session_ids: set[str],
) -> list[AgentSession]:
    filters = [AgentSession.id.not_in(excluded_session_ids)]
    if identity.project_id:
        filters.append(AgentSession.project_id == identity.project_id)
    rows = (
        (
            await db.execute(
                select(AgentSession)
                .where(*filters)
                .order_by(AgentSession.started_at.desc(), AgentSession.id.desc())
                .limit(BASELINE_SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    matches: list[AgentSession] = []
    for session in rows:
        candidate = workflow_identity_from_session(session)
        if not _same_workflow_identity(identity, candidate):
            continue
        matches.append(session)
        if len(matches) >= BASELINE_SESSION_LIMIT:
            break
    return matches


def _average_metrics(values: list[SessionUsageMetrics]) -> SessionUsageMetrics:
    if not values:
        return SessionUsageMetrics()
    sample_count = len(values)
    return SessionUsageMetrics(
        input_tokens=_round_metric(sum(item.input_tokens for item in values) / sample_count),
        output_tokens=_round_metric(sum(item.output_tokens for item in values) / sample_count),
        total_cost=sum(item.total_cost for item in values) / sample_count,
        llm_request_count=_round_metric(sum(item.llm_request_count for item in values) / sample_count),
        tool_call_count=_round_metric(sum(item.tool_call_count for item in values) / sample_count),
        turn_trace_count=_round_metric(sum(item.turn_trace_count for item in values) / sample_count),
    )


def _serialize_metrics(metrics: SessionUsageMetrics) -> dict[str, Any]:
    return {
        "input_tokens": metrics.input_tokens,
        "output_tokens": metrics.output_tokens,
        "total_tokens": metrics.total_tokens,
        "total_cost": metrics.total_cost,
        "llm_request_count": metrics.llm_request_count,
        "tool_call_count": metrics.tool_call_count,
        "deterministic_step_count": metrics.deterministic_step_count,
    }


def _same_workflow_identity(left: WorkflowIdentity, right: WorkflowIdentity) -> bool:
    if left.workflow_id and right.workflow_id:
        return left.workflow_id == right.workflow_id
    if left.workflow_class and right.workflow_class:
        return left.workflow_class == right.workflow_class
    return False


def _reduction_percent(baseline_value: float | int, current_value: float | int) -> float:
    baseline_number = float(baseline_value or 0)
    if baseline_number <= 0:
        return 0.0
    return (baseline_number - float(current_value or 0)) / baseline_number


def _round_metric(value: float) -> int:
    return int(value + 0.5)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
