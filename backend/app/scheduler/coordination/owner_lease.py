"""The single schedule-registration owner lease with an epoch fence."""

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
    return await _locked_lease(db, share=True) == (process_id, epoch, True)


async def read_lease(db: AsyncSession) -> LeaseState | None:
    row = (await db.execute(select(SchedulerOwnerLease).where(SchedulerOwnerLease.id == LEASE_ID))).scalar_one_or_none()
    if row is None:
        return None
    now = await db_now(db)
    return LeaseState(epoch=int(row.epoch), expires_at=row.expires_at, live=row.expires_at > now)
