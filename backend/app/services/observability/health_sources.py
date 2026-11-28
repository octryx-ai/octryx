"""Health rows of the things outside the process: connections, syncs, providers."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    ConnectorHealth,
    ConnectorHealthLog,
    KnowledgeSourceConnector,
    KnowledgeSourceSyncRun,
    Project,
    TurnTraceSummary,
)
from ...time_utils import ensure_utc

OK, DEGRADED, FAILING, UNKNOWN, DISABLED = "ok", "degraded", "failing", "unknown", "disabled"
STATUSES = (OK, DEGRADED, FAILING, UNKNOWN, DISABLED)
CONNECTION_STALE = timedelta(hours=1)
PROVIDER_WINDOW = timedelta(hours=1)
_CONNECTOR_STATUS = {"ok": OK, "healthy": OK, "error": FAILING, "failed": FAILING, "degraded": DEGRADED,
                     "warning": DEGRADED, "disabled": DISABLED}
_SYNC_FAILED = {"failed", "error"}
_SYNC_DEGRADED = {"needs_configuration", "budget_exhausted"}
# Rows written by gates and devices are not provider calls.
_NOT_PROVIDERS = {"", "execution-gate", "runtime-readiness-gate", "device"}


def iso(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


def row(component: str, status: str, *, since: datetime | None = None, last_check: datetime | None = None,
        detail: str = "", link: dict[str, str] | None = None) -> dict[str, Any]:
    return {"component": component, "status": status, "since": iso(since), "last_check": iso(last_check),
            "detail": detail, "link": link}


def _stale(checked: datetime | None, limit: timedelta, now: datetime) -> bool:
    return checked is None or ensure_utc(now) - ensure_utc(checked) > limit


async def _streak_start(db: AsyncSession, item: ConnectorHealth) -> tuple[datetime | None, int]:
    same = and_(ConnectorHealthLog.connector_name == item.connector_name,
                ConnectorHealthLog.project_id == (item.project_id or ""))
    last_other = (await db.execute(select(func.max(ConnectorHealthLog.checked_at)).where(
        same, ConnectorHealthLog.status != item.status))).scalar()
    since_clause = ConnectorHealthLog.checked_at > last_other if last_other is not None else True
    started, count = (await db.execute(select(func.min(ConnectorHealthLog.checked_at), func.count()).where(
        same, ConnectorHealthLog.status == item.status, since_clause))).one()
    return started, int(count or 0)


async def connection_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    names = {project_id: name for project_id, name in (await db.execute(select(Project.id, Project.name))).all()}
    rows = []
    for item in (await db.execute(select(ConnectorHealth).order_by(ConnectorHealth.connector_name))).scalars():
        status = _CONNECTOR_STATUS.get(str(item.status or "").lower(), UNKNOWN)
        if status != DISABLED and _stale(item.last_checked, CONNECTION_STALE, now):
            status = UNKNOWN
        since, streak = await _streak_start(db, item) if status in (FAILING, DEGRADED) else (None, 0)
        scope = names.get(item.project_id or "", "global") if item.project_id else "global"
        detail = (str(item.error or "")[:160] + (f" · {streak} failed checks" if streak else "")).strip(" ·") or "–"
        rows.append(row(f"{item.connector_name} · {scope}", status, since=since, last_check=item.last_checked,
                        detail=detail if status != OK else "–",
                        link={"tab": "connectors", "label": "Automation → Connectors"}))
    return rows


async def sync_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    latest = (select(KnowledgeSourceSyncRun.connector_id, func.max(KnowledgeSourceSyncRun.started_at).label("last"))
              .group_by(KnowledgeSourceSyncRun.connector_id).subquery())
    result = []
    for run, key, workspace in (await db.execute(
        select(KnowledgeSourceSyncRun, KnowledgeSourceConnector.connector_key, Project.name)
        .join(latest, and_(latest.c.connector_id == KnowledgeSourceSyncRun.connector_id,
                           latest.c.last == KnowledgeSourceSyncRun.started_at))
        .outerjoin(KnowledgeSourceConnector, KnowledgeSourceConnector.id == KnowledgeSourceSyncRun.connector_id)
        .outerjoin(Project, Project.id == KnowledgeSourceSyncRun.project_id)
    )).all():
        state = str(run.state or "")
        if state in _SYNC_FAILED:
            status, detail = FAILING, str(run.reason or state)
        elif state in _SYNC_DEGRADED:
            status, detail = DEGRADED, str(run.reason or state).replace("_", " ")
        elif state == "running" and ensure_utc(now) - ensure_utc(run.started_at) > timedelta(hours=2):
            status, detail = DEGRADED, "running for more than 2 h"
        else:
            status, detail = OK, state or "–"
        label = f"Knowledge sync {key or run.connector_id} · {workspace or 'Workspace'}"
        result.append(row(label, status, since=run.started_at,
                          last_check=run.finished_at or run.started_at, detail=detail,
                          link={"tab": "knowledgeSources", "label": "Knowledge → Sources"}))
    return result


def _percentile(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * share))]


async def provider_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    since = now - PROVIDER_WINDOW
    samples: dict[tuple[str, str], list[int]] = defaultdict(list)
    calls: dict[tuple[str, str], int] = defaultdict(int)
    failed: dict[tuple[str, str], int] = defaultdict(int)
    last_seen: dict[tuple[str, str], datetime] = {}
    previous: dict[str, datetime] = {}
    summary = TurnTraceSummary
    for provider, model, outcome, run_key, started, created in (await db.execute(
        select(summary.provider, summary.model, summary.outcome, summary.run_key, summary.started_at,
               summary.created_at)
        .where(summary.created_at >= since).order_by(summary.created_at)
    )).all():
        if (provider or "") in _NOT_PROVIDERS:
            continue
        key = (provider or "", model or "")
        calls[key] += 1
        failed[key] += int(outcome == "failed")
        last_seen[key] = created
        begin = previous.get(run_key) or started
        if begin is not None:
            samples[key].append(max(0, int((ensure_utc(created) - ensure_utc(begin)).total_seconds() * 1000)))
        previous[str(run_key)] = created
    rows = []
    for key in sorted(calls):
        error_rate = failed[key] / calls[key]
        p50, p95 = _percentile(samples[key], 0.5), _percentile(samples[key], 0.95)
        status = (FAILING if calls[key] >= 3 and error_rate >= 0.5
                  else DEGRADED if error_rate >= 0.05 or (p95 or 0) > 30_000 else OK)
        measured = p50 is not None and p95 is not None
        latency = f"p50 {p50 / 1000:.1f} s · p95 {p95 / 1000:.1f} s · " if measured else ""
        rows.append(row(f"{key[0]} · {key[1] or 'default model'}", status, last_check=last_seen[key],
                        detail=f"{latency}{calls[key]} calls · {round(error_rate * 100)} % errors",
                        link={"tab": "providers", "label": "Runtime → Providers"}))
    return rows


__all__ = ["STATUSES", "connection_rows", "iso", "provider_rows", "row", "sync_rows"]
