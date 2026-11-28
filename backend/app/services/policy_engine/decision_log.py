"""The policy decision log: bounded, OCSF-like records of the decisions worth reading."""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicyDecisionLog, SystemConfig
from ...time_utils import utc_now
from .schema import SCHEMA_VERSION

RETENTION_CONFIG_KEY = "policy_engine.decision_log_retention_days"
DEFAULT_RETENTION_DAYS = 365  # decisions are kept a year
MAX_RETENTION_DAYS = 365
MAX_ROWS = 100_000
BUFFER_SIZE = 2000
PRUNE_SECONDS = 3600.0
MAX_PAGE = 200
OUTCOME_DROPPED = "dropped"
POINT_DECISION_LOG = "decision_log"
ERROR_RECORDS_DROPPED = "decision_log_records_dropped"

_BUFFER: deque[dict[str, Any]] = deque(maxlen=BUFFER_SIZE)
_STATE: dict[str, Any] = {"dropped": 0, "reported": 0, "last_drop_at": None, "last_prune": 0.0}


def record_decision(entry: dict[str, Any]) -> None:
    if not entry.get("run_key"):
        # The run the decision belongs to: the in-app turn of the current request.
        from ..request_context import get_current_request_id

        request_id = get_current_request_id()
        entry["run_key"] = f"req:{request_id}"[:120] if request_id else None
    if len(_BUFFER) == _BUFFER.maxlen:
        _STATE["dropped"] += 1
        _STATE["last_drop_at"] = utc_now()
    _BUFFER.append(entry)


def pending_records() -> int:
    return len(_BUFFER)


def dropped_records() -> int:
    return int(_STATE["dropped"])


def dropped_since(since: datetime) -> bool:
    last = _STATE["last_drop_at"]
    return bool(_STATE["dropped"]) and last is not None and last >= since


def reset_dropped_records() -> None:
    _STATE["dropped"], _STATE["reported"], _STATE["last_drop_at"] = 0, 0, None


def clear_decision_buffer() -> None:
    _BUFFER.clear()
    reset_dropped_records()


def _dropped_marker(count: int) -> dict[str, Any]:
    from .runtime import current_runtime

    return {
        "created_at": utc_now(), "point": POINT_DECISION_LOG, "action": "record_decision", "outcome": OUTCOME_DROPPED,
        "mode": current_runtime().mode, "principal": "system", "resource": f"{count} decision records dropped",
        "decision": "none", "legacy_decision": "none", "determining": [], "errors": [ERROR_RECORDS_DROPPED],
        "schema_version": SCHEMA_VERSION, "latency_us": 0,
    }


async def retention_days(db: AsyncSession) -> int:
    row = await db.get(SystemConfig, RETENTION_CONFIG_KEY)
    try:
        days = int(str(row.value).strip()) if row is not None and row.value else DEFAULT_RETENTION_DAYS
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return days if 1 <= days <= MAX_RETENTION_DAYS else DEFAULT_RETENTION_DAYS


async def prune_decision_log(db: AsyncSession, *, now: datetime | None = None) -> None:
    cutoff = (now or utc_now()) - timedelta(days=await retention_days(db))
    await db.execute(delete(PolicyDecisionLog).where(PolicyDecisionLog.created_at < cutoff))
    total = (await db.execute(select(func.count()).select_from(PolicyDecisionLog))).scalar_one()
    if total > MAX_ROWS:
        oldest = (
            select(PolicyDecisionLog.id).order_by(PolicyDecisionLog.created_at.asc()).limit(total - MAX_ROWS)
        )
        await db.execute(delete(PolicyDecisionLog).where(PolicyDecisionLog.id.in_(oldest)))


async def _write(db: AsyncSession, entries: list[dict[str, Any]], *, prune: bool) -> None:
    db.add_all(PolicyDecisionLog(**entry) for entry in entries)
    await db.flush()
    if prune:
        await prune_decision_log(db)


async def flush_decision_log(db: AsyncSession | None = None, *, prune: bool | None = None) -> int:
    entries: list[dict[str, Any]] = []
    while _BUFFER:
        entries.append(_BUFFER.popleft())
    unreported = int(_STATE["dropped"]) - int(_STATE["reported"])
    if unreported > 0:
        entries.append(_dropped_marker(unreported))
        _STATE["reported"] = _STATE["dropped"]
    now = time.monotonic()
    should_prune = prune if prune is not None else now - _STATE["last_prune"] >= PRUNE_SECONDS
    if not entries and not should_prune:
        return 0
    if should_prune:
        _STATE["last_prune"] = now
    if db is not None:
        await _write(db, entries, prune=should_prune)
        return len(entries)
    from ...db import core as db_core

    try:
        async with db_core.async_session_factory() as session:
            await _write(session, entries, prune=should_prune)
            await session.commit()
    except Exception:
        _BUFFER.extendleft(reversed(entries[-BUFFER_SIZE:]))  # keep them for the next flush (bounded)
        raise
    return len(entries)


def serialize_decision(row: PolicyDecisionLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "time": row.created_at.isoformat() if row.created_at else None,
        "class_name": "Authorization",
        "point": row.point,
        "mode": row.mode,
        "outcome": row.outcome,
        "actor": {"principal": row.principal},
        "action": row.action,
        "resource": row.resource,
        "workspace_id": row.workspace_id,
        "decision": row.decision,
        "determining_policies": list(row.determining or []),
        "errors": list(row.errors or []),
        "legacy": {"decision": row.legacy_decision, "reason": row.legacy_reason},
        "policy_set": {
            "digest": row.policy_set_digest,
            "custom_version": row.custom_version,
            "schema_version": row.schema_version,
        },
        "latency_ms": round((row.latency_us or 0) / 1000, 3),
        "content": row.content,
        "obligation": row.obligation,
    }


async def query_decisions(
    db: AsyncSession,
    *,
    point: str | None = None,
    outcome: str | None = None,
    workspace_id: str | None = None,
    action: str | None = None,
    policy_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PolicyDecisionLog], int]:
    stmt = select(PolicyDecisionLog)
    for column, value in ((PolicyDecisionLog.point, point), (PolicyDecisionLog.outcome, outcome),
                          (PolicyDecisionLog.workspace_id, workspace_id), (PolicyDecisionLog.action, action)):
        if value:
            stmt = stmt.where(column == value)
    if since is not None:
        stmt = stmt.where(PolicyDecisionLog.created_at >= since)
    if until is not None:
        stmt = stmt.where(PolicyDecisionLog.created_at < until)
    page = max(1, min(int(limit), MAX_PAGE))
    start = max(0, int(offset))
    ordered = stmt.order_by(PolicyDecisionLog.created_at.desc(), PolicyDecisionLog.id.desc())
    if not policy_id:
        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
        return list((await db.execute(ordered.offset(start).limit(page))).scalars()), int(total)
    # JSON containment differs per dialect; the filtered set is bounded by retention (MAX_ROWS).
    rows = [row for row in (await db.execute(ordered)).scalars() if policy_id in (row.determining or [])]
    return rows[start:start + page], len(rows)


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "ERROR_RECORDS_DROPPED",
    "MAX_ROWS",
    "OUTCOME_DROPPED",
    "RETENTION_CONFIG_KEY",
    "clear_decision_buffer",
    "dropped_records",
    "dropped_since",
    "flush_decision_log",
    "pending_records",
    "prune_decision_log",
    "query_decisions",
    "record_decision",
    "reset_dropped_records",
    "retention_days",
    "serialize_decision",
]
