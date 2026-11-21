"""Per-connector circuit breaker state: check, record success or failure, and list."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import CircuitBreakerState
from ...time_utils import ensure_utc, utc_now, utc_now_aware
from .policy import CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_RETRY_DELAYS_SECONDS, CircuitBreakerDecision


async def get_or_create_circuit_breaker(db: AsyncSession, connector_name: str) -> CircuitBreakerState:
    entry = await db.get(CircuitBreakerState, connector_name)
    if entry is None:
        entry = CircuitBreakerState(connector_name=connector_name)
        db.add(entry)
        await db.flush()
    return entry


async def check_circuit_breaker(db: AsyncSession, connector_name: str) -> CircuitBreakerDecision:
    entry = await db.get(CircuitBreakerState, connector_name)
    if entry is None:
        return CircuitBreakerDecision(True, connector_name, "closed")

    now = utc_now_aware()
    next_retry_at = ensure_utc(entry.next_retry_at)
    if entry.state == "open":
        if next_retry_at and next_retry_at > now:
            return CircuitBreakerDecision(
                False,
                connector_name,
                "open",
                reason=f"Circuit breaker is open for {connector_name}",
                next_retry_at=next_retry_at.isoformat(),
            )
        entry.state = "half_open"
        await db.commit()
        return CircuitBreakerDecision(True, connector_name, "half_open")
    return CircuitBreakerDecision(True, connector_name, entry.state)


async def record_circuit_breaker_success(db: AsyncSession, connector_name: str) -> None:
    entry = await db.get(CircuitBreakerState, connector_name)
    if entry is None:
        return
    entry.state = "closed"
    entry.failure_count = 0
    entry.next_retry_at = None
    entry.last_error = None
    await db.commit()


async def record_circuit_breaker_failure(db: AsyncSession, connector_name: str, error: str) -> CircuitBreakerState:
    entry = await get_or_create_circuit_breaker(db, connector_name)
    entry.failure_count = int(entry.failure_count or 0) + 1
    entry.last_error = (error or "").strip()[:2000] or None
    if entry.failure_count >= CIRCUIT_BREAKER_FAILURE_THRESHOLD or entry.state in {"open", "half_open"}:
        attempt_index = max(
            0,
            min(
                entry.failure_count - CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                len(CIRCUIT_BREAKER_RETRY_DELAYS_SECONDS) - 1,
            ),
        )
        entry.state = "open"
        entry.next_retry_at = utc_now() + timedelta(seconds=CIRCUIT_BREAKER_RETRY_DELAYS_SECONDS[attempt_index])
    else:
        entry.state = "closed"
        entry.next_retry_at = None
    await db.commit()
    return entry


async def list_circuit_breakers(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(CircuitBreakerState).order_by(
                    CircuitBreakerState.state.asc(),
                    CircuitBreakerState.connector_name.asc(),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "connector_name": row.connector_name,
            "state": row.state,
            "failure_count": int(row.failure_count or 0),
            "next_retry_at": row.next_retry_at.isoformat() if row.next_retry_at else None,
            "last_error": row.last_error,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]
