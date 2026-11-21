from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentTraceRun, AgentTraceSpan
from ..time_utils import utc_now
from .redaction_policy import REDACTED_SECRET, redact_secret_payload

REDACTED_VALUE = REDACTED_SECRET


def _new_id() -> str:
    return str(uuid.uuid4())


def redact_trace_payload(value: Any) -> Any:
    """Remove secrets before trace payloads are persisted or returned."""

    return redact_secret_payload(value)


def _redacted_trace_error(value: Any) -> str | None:
    message = str(value or "")
    if not message:
        return None
    redacted = redact_trace_payload({"error": message})
    if isinstance(redacted, Mapping):
        return str(redacted.get("error") or "") or None
    return message


def _duration_ms(started_at: datetime | None, ended_at: datetime | None) -> int | None:
    if not started_at or not ended_at:
        return None
    return max(0, int((ended_at - started_at).total_seconds() * 1000))


def _decimal_to_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def serialize_trace_run(run: AgentTraceRun, *, include_spans: bool = False) -> dict[str, Any]:
    payload = {
        "id": run.id,
        "trace_id": run.trace_id,
        "session_id": run.session_id,
        "message_id": run.message_id,
        "project_id": run.project_id,
        "agent_definition_id": run.agent_definition_id,
        "flow_id": run.flow_id,
        "run_kind": run.run_kind,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "duration_ms": run.duration_ms,
        "input_tokens": run.input_tokens or 0,
        "output_tokens": run.output_tokens or 0,
        "total_tokens": run.total_tokens or 0,
        "cost": _decimal_to_float(run.cost),
        # False when the run's source records no duration/cost (shown as "not recorded", not 0).
        "duration_recorded": run.duration_ms is not None,
        "cost_recorded": bool((run.trace_metadata or {}).get("cost_recorded", True)),
        "quality_score": _decimal_to_float(run.quality_score) if run.quality_score is not None else None,
        "error": _redacted_trace_error(run.error),
        "metadata": redact_trace_payload(run.trace_metadata or {}),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }
    if include_spans:
        payload["spans"] = [serialize_trace_span(span) for span in sorted(run.spans, key=lambda item: item.started_at)]
    return payload


def serialize_trace_span(span: AgentTraceSpan) -> dict[str, Any]:
    return {
        "id": span.id,
        "trace_run_id": span.trace_run_id,
        "trace_id": span.trace_id,
        "span_id": span.span_id,
        "parent_span_id": span.parent_span_id,
        "span_type": span.span_type,
        "name": span.name,
        "status": span.status,
        "started_at": span.started_at.isoformat() if span.started_at else None,
        "ended_at": span.ended_at.isoformat() if span.ended_at else None,
        "duration_ms": span.duration_ms,
        "input_tokens": span.input_tokens or 0,
        "output_tokens": span.output_tokens or 0,
        "cost": _decimal_to_float(span.cost),
        "input": redact_trace_payload(span.input_json or {}),
        "output": redact_trace_payload(span.output_json or {}),
        "metadata": redact_trace_payload(span.span_metadata or {}),
        "error": _redacted_trace_error(span.error),
        "created_at": span.created_at.isoformat() if span.created_at else None,
    }


async def create_trace_run(
    db: AsyncSession,
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    message_id: str | None = None,
    project_id: str | None = None,
    agent_definition_id: str | None = None,
    flow_id: str | None = None,
    run_kind: str = "agent",
    status: str = "running",
    started_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> AgentTraceRun:
    now = utc_now()
    run = AgentTraceRun(
        id=_new_id(),
        trace_id=trace_id or _new_id(),
        session_id=session_id,
        message_id=message_id,
        project_id=project_id,
        agent_definition_id=agent_definition_id,
        flow_id=flow_id,
        run_kind=run_kind,
        status=status,
        started_at=started_at or now,
        trace_metadata=redact_trace_payload(metadata or {}),
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    await db.flush()
    return run


async def create_trace_span(
    db: AsyncSession,
    *,
    trace_run_id: str,
    span_type: str,
    name: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    status: str = "running",
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost: float | Decimal = 0,
    input_json: dict[str, Any] | None = None,
    output_json: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    error: str | None = None,
) -> AgentTraceSpan:
    run = await db.get(AgentTraceRun, trace_run_id)
    if run is None:
        raise ValueError(f"Trace run not found: {trace_run_id}")
    started = started_at or utc_now()
    span = AgentTraceSpan(
        id=_new_id(),
        trace_run_id=trace_run_id,
        trace_id=run.trace_id,
        span_id=span_id or _new_id(),
        parent_span_id=parent_span_id,
        span_type=span_type,
        name=name,
        status=status,
        started_at=started,
        ended_at=ended_at,
        duration_ms=_duration_ms(started, ended_at),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cost,
        input_json=redact_trace_payload(input_json or {}),
        output_json=redact_trace_payload(output_json or {}),
        span_metadata=redact_trace_payload(metadata or {}),
        error=_redacted_trace_error(error),
        created_at=utc_now(),
    )
    db.add(span)
    await db.flush()
    return span


async def finish_trace_run(
    db: AsyncSession,
    *,
    trace_run_id: str,
    status: str = "success",
    ended_at: datetime | None = None,
    quality_score: float | None = None,
    error: str | None = None,
) -> AgentTraceRun:
    run = await db.get(AgentTraceRun, trace_run_id)
    if run is None:
        raise ValueError(f"Trace run not found: {trace_run_id}")
    ended = ended_at or utc_now()
    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(AgentTraceSpan.input_tokens), 0),
                func.coalesce(func.sum(AgentTraceSpan.output_tokens), 0),
                func.coalesce(func.sum(AgentTraceSpan.cost), 0),
            ).where(AgentTraceSpan.trace_run_id == trace_run_id)
        )
    ).one()
    run.status = status
    run.ended_at = ended
    run.duration_ms = _duration_ms(run.started_at, ended)
    run.input_tokens = int(totals[0] or 0)
    run.output_tokens = int(totals[1] or 0)
    run.total_tokens = run.input_tokens + run.output_tokens
    run.cost = totals[2] or 0
    run.quality_score = quality_score
    run.error = _redacted_trace_error(error)
    run.updated_at = utc_now()
    await db.flush()
    return run


async def get_trace_run_detail(
    db: AsyncSession,
    *,
    trace_run_id: str,
    project_id: str | None = None,
    span_limit: int = 500,
) -> dict[str, Any] | None:
    run = await db.get(AgentTraceRun, trace_run_id)
    if run is None:
        return None
    if project_id and run.project_id != project_id:
        return None
    bounded_span_limit = max(1, min(1000, int(span_limit or 500)))
    spans = (
        await db.execute(
            select(AgentTraceSpan)
            .where(AgentTraceSpan.trace_run_id == trace_run_id)
            .order_by(AgentTraceSpan.started_at.asc())
            .limit(bounded_span_limit + 1)
        )
    ).scalars().all()
    spans_truncated = len(spans) > bounded_span_limit
    payload = serialize_trace_run(run)
    payload["span_limit"] = bounded_span_limit
    payload["spans_truncated"] = spans_truncated
    payload["spans"] = [serialize_trace_span(span) for span in spans[:bounded_span_limit]]
    return payload

