"""Observability → Runs: every run of every source, read from ``turn_traces`` + ``tool_calls`` (O1).

A run is the set of ``turn_traces`` rows whose summaries (``turn_trace_summaries``) share a ``run_key``. The list
groups and filters in SQL over a bounded window and pages server-side; it never loads trace JSON. Tool counts come
from ``tool_calls`` of the run (the same rows the chat shows), cost from ``usage_events`` (the one cost source). The
run's outcome is its newest row's outcome.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ...models import Project, Session, ToolCall, TurnTrace, TurnTraceSummary, UsageEvent, User
from ...time_utils import ensure_utc, utc_now
from .cost_states import cost_state_expression, run_cost_state
from .run_summary import ORIGINS_BY_SOURCE, RUN_OUTCOMES, source_for_origin

WINDOW_HOURS = (1, 24, 168)
DEFAULT_WINDOW_HOURS = 24
MAX_PAGE_SIZE = 100
TOOL_OK = "success"


def _iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def _duration_ms(started: datetime | None, ended: datetime | None) -> int | None:
    if started is None or ended is None:
        return None
    return max(0, int((ensure_utc(ended) - ensure_utc(started)).total_seconds() * 1000))


def _runs_statement(since: datetime):
    summary = TurnTraceSummary
    grouped = (
        select(
            summary.run_key.label("run_key"),
            func.max(summary.session_id).label("session_id"),
            func.min(summary.started_at).label("started_at"),
            func.min(summary.created_at).label("first_at"),
            func.max(summary.created_at).label("last_at"),
            func.count(summary.trace_id).label("steps"),
            func.max(summary.agent_label).label("agent_label"),
        )
        # The trace itself must still exist (retention deletes traces; their summaries follow).
        .join(TurnTrace, TurnTrace.id == summary.trace_id)
        .where(summary.created_at >= since)
        .group_by(summary.run_key)
        .subquery()
    )
    newest = aliased(TurnTraceSummary)
    outcome = (
        select(newest.outcome)
        .where(newest.run_key == grouped.c.run_key)
        .order_by(newest.created_at.desc(), newest.trace_id.desc())
        .limit(1)
        .correlate(grouped)
        .scalar_subquery()
    )
    statement = (
        select(
            grouped,
            outcome.label("outcome"),
            Session.user_id,
            Session.project_id,
            Session.origin,
            User.username,
            User.display_name,
            Project.name.label("project_name"),
        )
        .join(Session, Session.id == grouped.c.session_id)
        .outerjoin(User, User.id == Session.user_id)
        .outerjoin(Project, Project.id == Session.project_id)
    )
    return statement, grouped, outcome


async def list_runs(
    db: AsyncSession,
    *,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    project_id: str | None = None,
    source: str | None = None,
    outcome: str | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    window_hours = window_hours if window_hours in WINDOW_HOURS else DEFAULT_WINDOW_HOURS
    page, page_size = max(1, page), max(1, min(MAX_PAGE_SIZE, page_size))
    since = utc_now() - timedelta(hours=window_hours)
    statement, grouped, outcome_expr = _runs_statement(since)
    # Runs in private Workspaces are their owner's alone: the admin's run list never shows them.
    private = aliased(Project)
    statement = statement.where(or_(Session.project_id.is_(None), Session.project_id.not_in(
        select(private.id).where(private.access_mode == "private").scalar_subquery())))
    total_in_window = int((await db.execute(select(func.count()).select_from(statement.subquery()))).scalar() or 0)
    if project_id:
        statement = statement.where(Session.project_id == project_id)
    if source in ORIGINS_BY_SOURCE:
        statement = statement.where(Session.origin.in_(ORIGINS_BY_SOURCE[source]))
    if outcome in RUN_OUTCOMES:
        statement = statement.where(outcome_expr == outcome)
    needle = (query or "").strip().lower()
    if needle:
        pattern = f"%{needle}%"
        statement = statement.where(or_(
            func.lower(User.username).like(pattern),
            func.lower(func.coalesce(User.display_name, "")).like(pattern),
            func.lower(func.coalesce(grouped.c.agent_label, "")).like(pattern),
        ))
    total = int((await db.execute(select(func.count()).select_from(statement.subquery()))).scalar() or 0)
    rows = (await db.execute(
        statement.order_by(grouped.c.last_at.desc(), grouped.c.run_key).limit(page_size).offset((page - 1) * page_size)
    )).all()
    tools = await _tool_counts(db, rows, since)
    costs = await _costs(db, rows, since)
    return {
        "window_hours": window_hours,
        "since": _iso(since),
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_in_window": total_in_window,
        "items": [_serialize_run(row, tools.get(row.run_key), costs.get(row.run_key)) for row in rows],
    }


def _serialize_run(row: Any, tools: tuple[int, int] | None, cost: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "run_key": row.run_key,
        "session_id": row.session_id,
        "time": _iso(row.last_at),
        "started_at": _iso(row.started_at),
        "duration_ms": _duration_ms(row.started_at, row.last_at),
        "workspace_id": row.project_id,
        "workspace_name": row.project_name,
        "user_id": row.user_id,
        "user_name": row.display_name or row.username,
        "agent_label": row.agent_label,
        "source": source_for_origin(row.origin),
        "outcome": row.outcome,
        "steps": int(row.steps or 0),
        "tool_count": tools[0] if tools else None,
        "tool_failed": tools[1] if tools else None,
        "cost": cost["cost"] if cost else None,
        "cost_state": cost["state"] if cost else None,
    }


def _keys(rows: list[Any], prefix: str) -> dict[str, Any]:
    return {row.run_key[len(prefix):]: row for row in rows if str(row.run_key).startswith(prefix)}


def _failed_count():
    return func.sum(case((ToolCall.status == TOOL_OK, 0), else_=1))


async def _tool_counts(db: AsyncSession, rows: list[Any], since: datetime) -> dict[str, tuple[int, int]]:
    """Tool calls per run: in-app by request id, gateway by session within the window (device runs: none)."""
    result: dict[str, tuple[int, int]] = {}
    requests = _keys(rows, "req:")
    if requests:
        for request_id, count, failed in (await db.execute(
            select(ToolCall.request_id, func.count(ToolCall.id), _failed_count())
            .where(ToolCall.request_id.in_(list(requests)))
            .group_by(ToolCall.request_id)
        )).all():
            result[requests[request_id].run_key] = (int(count), int(failed or 0))
        for row in requests.values():
            result.setdefault(row.run_key, (0, 0))
    gateways = _keys(rows, "gw:")
    if gateways:
        for session_id, count, failed in (await db.execute(
            select(ToolCall.session_id, func.count(ToolCall.id), _failed_count())
            .where(ToolCall.session_id.in_(list(gateways)), ToolCall.created_at >= since)
            .group_by(ToolCall.session_id)
        )).all():
            result[gateways[session_id].run_key] = (int(count), int(failed or 0))
        for row in gateways.values():
            result.setdefault(row.run_key, (0, 0))
    return result


async def _costs(db: AsyncSession, rows: list[Any], since: datetime) -> dict[str, dict[str, Any]]:
    """Cost per run from ``usage_events``: in-app by request id, gateway by session within the window."""
    state = cost_state_expression()
    sums: dict[str, float] = defaultdict(float)
    states: dict[str, set[str]] = defaultdict(set)
    requests = _keys(rows, "req:")
    if requests:
        for request_id, row_state, cost in (await db.execute(
            select(UsageEvent.request_id, state, func.coalesce(func.sum(UsageEvent.cost), 0))
            .where(UsageEvent.request_id.in_(list(requests)))
            .group_by(UsageEvent.request_id, state)
        )).all():
            key = requests[request_id].run_key
            sums[key] += float(cost or 0)
            states[key].add(row_state)
    gateways = _keys(rows, "gw:")
    if gateways:
        for session_id, row_state, cost in (await db.execute(
            select(UsageEvent.session_id, state, func.coalesce(func.sum(UsageEvent.cost), 0))
            .where(UsageEvent.session_id.in_(list(gateways)), UsageEvent.created_at >= since)
            .group_by(UsageEvent.session_id, state)
        )).all():
            key = gateways[session_id].run_key
            sums[key] += float(cost or 0)
            states[key].add(row_state)
    for row in rows:
        if str(row.run_key).startswith("dev:"):
            states[row.run_key].add("not_billed")
    return {key: {"cost": round(sums[key], 6), "state": run_cost_state(found)} for key, found in states.items()}




async def run_metrics(db: AsyncSession, *, window_hours: int = DEFAULT_WINDOW_HOURS) -> dict[str, Any]:
    """Runs per outcome and measured run durations in the window (for ``/metrics``), all from SQL."""
    since = utc_now() - timedelta(hours=window_hours)
    statement, grouped, _outcome = _runs_statement(since)
    runs = statement.subquery()
    by_outcome = {
        str(name or "unknown"): int(count)
        for name, count in (await db.execute(select(runs.c.outcome, func.count()).group_by(runs.c.outcome))).all()
    }
    durations = [
        duration
        for duration in (_duration_ms(started, ended) for started, ended in (await db.execute(
            select(grouped.c.started_at, grouped.c.last_at).where(grouped.c.started_at.is_not(None))
        )).all())
        if duration is not None
    ]
    return {"window_hours": window_hours, "by_outcome": by_outcome, "durations_ms": durations}


__all__ = ["DEFAULT_WINDOW_HOURS", "WINDOW_HOURS", "list_runs", "run_metrics"]
