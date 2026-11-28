"""Renew, read and release platform process liveness leases (runtime robustness R1)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.runtime.process_lease import RuntimeProcessLease
from ..knowledge.ledger.database_clock import database_now
from .process_identity import current_process_id

# The heartbeat renews well inside the lease window, so one missed heartbeat
# (a slow database round trip) never makes a live process look dead.
PROCESS_LEASE_TTL = timedelta(seconds=90)
PROCESS_LEASE_HEARTBEAT_SECONDS = 20
# Expired rows are kept for a while for diagnosis, then pruned by the sweep.
EXPIRED_LEASE_RETENTION = timedelta(days=1)


async def renew_process_lease(db: AsyncSession, *, ttl: timedelta = PROCESS_LEASE_TTL) -> str:
    process_id = current_process_id()
    now = await database_now(db)
    renewed = await db.execute(
        update(RuntimeProcessLease)
        .where(RuntimeProcessLease.id == process_id)
        .values(heartbeat_at=now, expires_at=now + ttl)
        .execution_options(synchronize_session=False)
    )
    if int(renewed.rowcount or 0) == 0:
        await db.execute(
            insert(RuntimeProcessLease).values(id=process_id, started_at=now, heartbeat_at=now, expires_at=now + ttl)
        )
    return process_id


async def release_process_lease(db: AsyncSession) -> None:
    await db.execute(
        delete(RuntimeProcessLease)
        .where(RuntimeProcessLease.id == current_process_id())
        .execution_options(synchronize_session=False)
    )


async def live_process_ids(db: AsyncSession, candidates: Iterable[str]) -> frozenset[str]:
    wanted = sorted({candidate for candidate in candidates if candidate})
    if not wanted:
        return frozenset()
    now = await database_now(db)
    rows = await db.execute(
        select(RuntimeProcessLease.id).where(RuntimeProcessLease.id.in_(wanted), RuntimeProcessLease.expires_at > now)
    )
    return frozenset(rows.scalars().all())


async def prune_expired_process_leases(db: AsyncSession, *, retention: timedelta = EXPIRED_LEASE_RETENTION) -> int:
    now = await database_now(db)
    pruned = await db.execute(
        delete(RuntimeProcessLease)
        .where(RuntimeProcessLease.expires_at < now - retention)
        .execution_options(synchronize_session=False)
    )
    return int(pruned.rowcount or 0)


__all__ = [
    "EXPIRED_LEASE_RETENTION",
    "PROCESS_LEASE_HEARTBEAT_SECONDS",
    "PROCESS_LEASE_TTL",
    "live_process_ids",
    "prune_expired_process_leases",
    "release_process_lease",
    "renew_process_lease",
]
