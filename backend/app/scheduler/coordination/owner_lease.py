"""The single schedule-registration owner lease with an epoch fence.

Every decision is made *after* the lease row lock is held, by a fresh read in the same transaction
(:func:`_locked_lease`): PostgreSQL does not re-evaluate a WHERE clause after a lock wait on a row
that was not modified, so a predicate inside the locking statement could approve a lease that
expired while waiting. Written deadlines are evaluated at write time (``deadline_expression``).

* **Acquire.** The first process inserts the singleton row with ``epoch=1`` and owns it at once; its
  instants are re-stamped from the database clock after the insert (which may have waited for a
  competing insert that rolled back), in the same transaction.
  Otherwise it locks the row, re-reads it with the current database clock, and takes it over only if
  it has expired then, incrementing the epoch.
* **Renew.** Lock, re-read; extend only for the same owner and epoch while still unexpired.
* **Admit** is the fence every owner write uses inside its own transaction: lock the lease row
  ``FOR SHARE``, then re-read owner, epoch and expiry against the current clock. A takeover or renew
  needs ``FOR UPDATE`` on that row and therefore waits until the admitted transaction ends. An
  admitted transaction may outlast ``expires_at`` while it holds the share lock; expiry does not
  cancel it, it only lets a takeover proceed after that transaction committed or rolled back. A
  refused admission writes nothing.

PostgreSQL row locks substantiate this; on SQLite (tests only) the checks hold, the locks do not
exist. Nothing here commits: callers own the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import SchedulerOwnerLease
from .clock import db_now, deadline_expression, now_expression

LEASE_ID = "task-scheduler"
DEFAULT_LEASE_TTL = timedelta(seconds=90)
DEFAULT_HEARTBEAT_SECONDS = 20.0


@dataclass(frozen=True)
class LeaseState:
    epoch: int
    expires_at: datetime
    live: bool


async def _locked_lease(db: AsyncSession, *, share: bool) -> tuple[str, int, bool] | None:
    """Lock the lease row, then read owner, epoch and liveness again with the current clock."""
    locked = (
        await db.execute(
            select(SchedulerOwnerLease.id).where(SchedulerOwnerLease.id == LEASE_ID).with_for_update(read=share)
        )
    ).scalar_one_or_none()
    if locked is None:
        return None
    # A separate statement after the lock is held: a fresh snapshot and a fresh clock reading.
    row = (
        await db.execute(
            select(
                SchedulerOwnerLease.owner_process_id,
                SchedulerOwnerLease.epoch,
                SchedulerOwnerLease.expires_at > now_expression(db),
            ).where(SchedulerOwnerLease.id == LEASE_ID)
        )
    ).one()
    return str(row[0]), int(row[1]), bool(row[2])


async def acquire_owner_lease(db: AsyncSession, *, process_id: str, ttl: timedelta = DEFAULT_LEASE_TTL) -> int | None:
    """This process's epoch when it now owns the lease, else ``None``."""
    now = await db_now(db)
    try:
        async with db.begin_nested():
            db.add(SchedulerOwnerLease(id=LEASE_ID, owner_process_id=process_id, epoch=1, acquired_at=now,
                                       heartbeat_at=now, expires_at=now + ttl))
            # The INSERT may have waited for a competing uncommitted INSERT (which then rolled back):
            # its values were formed before that wait. Re-stamp the row we now hold with the clock
            # at this point, in the same transaction, so a first owner never holds an expired lease.
            await db.flush()
            await db.execute(
                update(SchedulerOwnerLease)
                .where(SchedulerOwnerLease.id == LEASE_ID, SchedulerOwnerLease.owner_process_id == process_id,
                       SchedulerOwnerLease.epoch == 1)
                .values(acquired_at=now_expression(db), heartbeat_at=now_expression(db),
                        expires_at=deadline_expression(db, ttl))
                .execution_options(synchronize_session=False)
            )
        return 1
    except IntegrityError:
        pass
    current = await _locked_lease(db, share=False)
    if current is None or current[2]:
        return None
    epoch = current[1] + 1
    await db.execute(
        update(SchedulerOwnerLease)
        .where(SchedulerOwnerLease.id == LEASE_ID)
        .values(owner_process_id=process_id, epoch=epoch, acquired_at=now_expression(db),
                heartbeat_at=now_expression(db), expires_at=deadline_expression(db, ttl))
        .execution_options(synchronize_session=False)
    )
    return epoch


async def renew_owner_lease(
    db: AsyncSession, *, process_id: str, epoch: int, ttl: timedelta = DEFAULT_LEASE_TTL
) -> bool:
    current = await _locked_lease(db, share=False)
    if current != (process_id, epoch, True):
        return False
    await db.execute(
        update(SchedulerOwnerLease)
        .where(SchedulerOwnerLease.id == LEASE_ID)
        .values(heartbeat_at=now_expression(db), expires_at=deadline_expression(db, ttl))
        .execution_options(synchronize_session=False)
    )
    return True


async def release_owner_lease(db: AsyncSession, *, process_id: str, epoch: int) -> None:
    """End this owner's lease on a clean shutdown so a successor need not wait for expiry."""
    current = await _locked_lease(db, share=False)
    if current is None or current[:2] != (process_id, epoch):
        return
    await db.execute(
        update(SchedulerOwnerLease)
        .where(SchedulerOwnerLease.id == LEASE_ID)
        .values(expires_at=now_expression(db))
        .execution_options(synchronize_session=False)
    )


async def admit_owner(db: AsyncSession, *, process_id: str, epoch: int) -> bool:
    """The fence: hold the lease row FOR SHARE and re-check owner, epoch and expiry after the lock."""
    return await _locked_lease(db, share=True) == (process_id, epoch, True)


async def read_lease(db: AsyncSession) -> LeaseState | None:
    """The current lease and whether it is live now, without any lock."""
    row = (await db.execute(select(SchedulerOwnerLease).where(SchedulerOwnerLease.id == LEASE_ID))).scalar_one_or_none()
    if row is None:
        return None
    now = await db_now(db)
    return LeaseState(epoch=int(row.epoch), expires_at=row.expires_at, live=row.expires_at > now)
