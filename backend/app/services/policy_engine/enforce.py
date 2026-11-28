"""The guarded switch from shadow to enforce."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PolicyDecisionLog, SystemConfig
from ...time_utils import utc_now
from .decision_log import OUTCOME_DROPPED, dropped_since, flush_decision_log, pending_records
from .engine import PolicyEngineUnavailableError, compiled_schema
from .runtime import MODE_ENFORCE, MODE_SHADOW, PolicyRuntime

logger = logging.getLogger(__name__)

WINDOW_CONFIG_KEY = "policy_engine.enforce_window_hours"
SHADOW_SINCE_CONFIG_KEY = "policy_engine.shadow_since"
DEFAULT_WINDOW_HOURS = 24
MAX_WINDOW_HOURS = 720

REASON_NOT_IN_SHADOW = "not_in_shadow"
REASON_WINDOW = "window_not_elapsed"
REASON_MISMATCHES = "mismatches_in_window"
REASON_ERRORS = "errors_in_window"
REASON_CUSTOM_INVALID = "custom_set_invalid"
REASON_ENGINE = "engine_unavailable"
REASON_PENDING = "decision_log_pending"
REASON_DROPPED = "decision_log_records_dropped"


async def _value(db: AsyncSession, key: str) -> str:
    row = await db.get(SystemConfig, key)
    return str(row.value).strip() if row is not None and row.value else ""


async def window_hours(db: AsyncSession) -> int:
    raw = await _value(db, WINDOW_CONFIG_KEY)
    try:
        hours = int(raw) if raw else DEFAULT_WINDOW_HOURS
    except ValueError:
        return DEFAULT_WINDOW_HOURS
    return hours if 1 <= hours <= MAX_WINDOW_HOURS else DEFAULT_WINDOW_HOURS


async def shadow_since(db: AsyncSession) -> datetime | None:
    raw = await _value(db, SHADOW_SINCE_CONFIG_KEY)
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


async def _count(db: AsyncSession, outcome: str, since: datetime) -> int:
    stmt = select(func.count()).select_from(PolicyDecisionLog).where(
        PolicyDecisionLog.outcome == outcome, PolicyDecisionLog.created_at >= since
    )
    return int((await db.execute(stmt)).scalar_one())


def _engine_available() -> bool:
    try:
        compiled_schema()
    except PolicyEngineUnavailableError:
        return False
    return True


async def _flushed() -> bool:
    try:
        await flush_decision_log(prune=False)
    except Exception:  # noqa: BLE001 - the records stay buffered; readiness then refuses
        logger.warning("policy_engine_readiness_flush_failed", exc_info=True)
    return pending_records() == 0


async def enforce_readiness(db: AsyncSession, runtime: PolicyRuntime, *, now: datetime | None = None) -> dict[str, Any]:
    flushed = await _flushed()
    current = now or utc_now()
    hours = await window_hours(db)
    since = await shadow_since(db)
    window_start = max(since, current - timedelta(hours=hours)) if since else current - timedelta(hours=hours)
    mismatches = await _count(db, "mismatch", window_start)
    errors = await _count(db, "error", window_start)
    drop_start = since or window_start
    dropped = await _count(db, OUTCOME_DROPPED, drop_start) or int(dropped_since(drop_start))
    reasons: list[str] = []
    if not _engine_available():
        reasons.append(REASON_ENGINE)
    if runtime.custom_invalid:
        reasons.append(REASON_CUSTOM_INVALID)
    if runtime.mode not in (MODE_SHADOW, MODE_ENFORCE):
        reasons.append(REASON_NOT_IN_SHADOW)
    elif runtime.mode == MODE_SHADOW and (since is None or current - since < timedelta(hours=hours)):
        reasons.append(REASON_WINDOW)
    if mismatches:
        reasons.append(REASON_MISMATCHES)
    if errors:
        reasons.append(REASON_ERRORS)
    if not flushed:
        reasons.append(REASON_PENDING)
    if dropped:
        reasons.append(REASON_DROPPED)
    return {
        "window_hours": hours,
        "shadow_since": since.isoformat() if since else None,
        "mismatches": mismatches,
        "errors": errors,
        "dropped_records": dropped,
        "ready": not reasons,
        "reasons": reasons,
    }


__all__ = [
    "DEFAULT_WINDOW_HOURS",
    "MAX_WINDOW_HOURS",
    "REASON_DROPPED",
    "SHADOW_SINCE_CONFIG_KEY",
    "WINDOW_CONFIG_KEY",
    "enforce_readiness",
    "shadow_since",
    "window_hours",
]
