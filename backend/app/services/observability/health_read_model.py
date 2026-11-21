"""Observability → Health (O4): one row per thing that can break, with a link to where it is fixed.

Groups: Platform (API, database, scheduler and every background worker), Connections, Syncs & intakes,
Providers (last hour), Background jobs (dead letters, circuit breakers, device clients). ``unknown`` and
``disabled`` are their own states: a worker that never started, a check that went stale or a component that is
switched off is never shown as ``ok``. Details stay with the owner; Health only rolls up.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import BackgroundWorkerRunState, CircuitBreakerState, DeviceJob, FailedTaskRun, UserDevice
from ...time_utils import ensure_utc, utc_now
from .health_sources import (
    DEGRADED,
    DISABLED,
    FAILING,
    OK,
    STATUSES,
    UNKNOWN,
    connection_rows,
    provider_rows,
    row,
    sync_rows,
)
from .request_metrics import recent_request_summary

WORKER_STALE = timedelta(hours=24)
# A worker idle because its part is not set up on this platform (no knowledge store): not a fault, never "failing"
# (a fresh demo stack would otherwise show "2 failing" in Operations › Overview). Its failure token -> what to say.
WORKER_NOT_SET_UP = {"not_configured": "not configured: no knowledge store is set up on this platform"}
DEVICE_ONLINE = timedelta(minutes=5)
_CHECK_STATUS = {"ok": OK, "degraded": DEGRADED, "error": FAILING, "unknown": UNKNOWN, "disabled": DISABLED}
_WORKER_FAILED = {"failed", "error"}
RUNTIME_LINK = {"tab": "runtimeExecution", "label": "Runtime → Execution & storage"}
SCHEDULER_LINK = {"tab": "schedulers", "label": "Automation → Schedulers"}


def _api_row(now: datetime) -> dict[str, Any]:
    summary = recent_request_summary()
    requests, errors = summary["requests"], summary["errors_5xx"]
    share = errors / requests if requests else 0.0
    status = FAILING if requests >= 20 and share >= 0.1 else DEGRADED if errors and share >= 0.01 else OK
    p95 = f"p95 {summary['p95_ms']} ms · " if summary["p95_ms"] is not None else ""
    return row("API", status, last_check=now, detail=f"{p95}{requests} requests · {errors} × 5xx in 1 h (this process)",
               link=RUNTIME_LINK)


def _component_rows(checks: dict[str, dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    rows = []
    for name, check in sorted(checks.items()):
        status = _CHECK_STATUS.get(str(check.get("status") or ""), UNKNOWN)
        detail = str(check.get("error") or "") or f"{check.get('response_time_ms', 0)} ms"
        rows.append(row(name.replace("_", " ").capitalize(), status, last_check=now, detail=detail,
                        link=SCHEDULER_LINK if "scheduler" in name or "task_queue" in name else RUNTIME_LINK))
    return rows


async def _worker_state_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    rows = []
    states = select(BackgroundWorkerRunState).order_by(BackgroundWorkerRunState.worker_name)
    for state in (await db.execute(states)).scalars():
        if ensure_utc(now) - ensure_utc(state.updated_at) > WORKER_STALE:
            status, detail = UNKNOWN, "not run for more than 24 h"
        elif str(state.status or "") in _WORKER_FAILED and str(state.error or "") in WORKER_NOT_SET_UP:
            status, detail = DISABLED, WORKER_NOT_SET_UP[str(state.error)]
        elif str(state.status or "") in _WORKER_FAILED:
            status, detail = FAILING, str(state.error or state.status)[:160]
        else:
            status, detail = OK, f"{state.run_count} runs · {state.failure_count} failures"
        rows.append(row(f"Worker {state.worker_name}", status, since=state.started_at, last_check=state.updated_at,
                        detail=detail, link=RUNTIME_LINK))
    return rows


async def _background_rows(db: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    week = now - timedelta(days=7)
    dead = int((await db.execute(select(func.count()).select_from(FailedTaskRun).where(
        FailedTaskRun.created_at >= week, FailedTaskRun.status != "resolved"))).scalar() or 0)
    breakers = (await db.execute(
        select(CircuitBreakerState.state, func.count()).group_by(CircuitBreakerState.state))).all()
    open_breakers = sum(int(count) for state, count in breakers if state != "closed")
    devices = (await db.execute(select(UserDevice.status, UserDevice.last_seen_at))).all()
    online = sum(1 for status, seen in devices
                 if status == "active" and seen is not None and ensure_utc(now) - ensure_utc(seen) <= DEVICE_ONLINE)
    revoked = sum(1 for status, _seen in devices if status != "active")
    lost = int((await db.execute(select(func.count()).select_from(DeviceJob).where(
        DeviceJob.status == "device_lost", DeviceJob.updated_at >= week))).scalar() or 0)
    return [
        row("Dead letters (7 d)", DEGRADED if dead else OK, last_check=now, detail=str(dead),
            link={"tab": "tasks", "label": "Automation → Actions"}),
        row("Circuit breakers", DEGRADED if open_breakers else OK, last_check=now,
            detail=f"{open_breakers} open · {sum(int(count) for _s, count in breakers) - open_breakers} closed",
            link={"tab": "connectors", "label": "Automation → Connectors"}),
        row("Device clients", DEGRADED if lost else OK, last_check=now,
            detail=f"{online} online · {revoked} revoked · {lost} jobs lost in 7 d",
            link={"href": "/chat?area=agents", "label": "Agents → Connected clients"}),
    ]


def _summary(groups: list[dict[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(STATUSES, 0)
    for group in groups:
        for item in group["rows"]:
            counts[item["status"]] += 1
    return counts


async def health_overview(db: AsyncSession, *, checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    now = utc_now()
    platform = [_api_row(now), *_component_rows(checks, now), *await _worker_state_rows(db, now)]
    groups = [
        {"key": "platform", "label": "Platform", "owner": "Runtime · Automation → Schedulers", "rows": platform},
        {"key": "connections", "label": "Connections", "owner": "Automation → Connectors",
         "rows": await connection_rows(db, now)},
        {"key": "syncs", "label": "Syncs & intakes", "owner": "Knowledge → Sources",
         "rows": await sync_rows(db, now)},
        {"key": "providers", "label": "Providers (last 1 h)", "owner": "Runtime → Providers",
         "rows": await provider_rows(db, now)},
        {"key": "background", "label": "Background jobs", "owner": "Automation",
         "rows": await _background_rows(db, now)},
    ]
    return {"checked_at": now.isoformat(), "summary": _summary(groups), "groups": groups}


__all__ = ["health_overview"]
