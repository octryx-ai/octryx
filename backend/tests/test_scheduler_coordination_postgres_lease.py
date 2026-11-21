"""On PostgreSQL an admitted fire's shared lease lock fences a takeover and a stale acknowledgement, a renew after waiting past expiry is refused, and a takeover's deadline is measured after the wait."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, text

from app.models import Scheduler, SchedulerJobApplication
from app.scheduler.coordination import owner_lease
from app.scheduler.coordination.application_status import scheduler_worker_applications
from tests.alembic_model_parity_support import requires_postgres
from tests.scheduler_coordination_postgres_support import (
    _owner,
    _runs,
    _scenario_test,
    _seed,
    _wait_blocked,
    _with_barrier,
)

pytestmark = requires_postgres


async def _fenced_takeover(maker):
    task_id, row_id, fp = await _seed(maker)
    sched = await _owner(maker, ttl=timedelta(seconds=2))
    entered, release = _with_barrier(sched)
    try:
        fire = asyncio.create_task(sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id))
        await asyncio.wait_for(entered.wait(), 15)
        await asyncio.sleep(2.5)  # the lease is now expired on the database clock

        async def take_over():
            async with maker() as db:
                epoch = await owner_lease.acquire_owner_lease(db, process_id="successor")
                await db.commit()
                return epoch

        takeover = asyncio.create_task(take_over())
        await _wait_blocked(maker)
        assert not takeover.done(), "the admitted fire blocks the takeover until it commits"
        release.set()
        assert (await fire)["status"] == "queued", "expiry does not cancel an admitted transaction"
        assert await takeover == 2
        assert await _runs(maker, task_id) == 1

        sched._insert_task_run = type(sched)._insert_task_run.__get__(sched)
        assert await sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id) is None
        assert await _runs(maker, task_id) == 1, "the old owner's later fire is refused"

        sched._coordinator.epoch = 1  # the old owner still believes it owns: its acknowledgement is refused
        await sched._coordinator.reconcile_once()
        assert sched._coordinator.epoch is None
        async with maker() as db:
            acks = (await db.execute(select(SchedulerJobApplication))).scalars().all()
            assert {ack.owner_epoch for ack in acks} == {1}
            row = await db.get(Scheduler, row_id)
            status = (await scheduler_worker_applications(db, [row]))[row_id]
        assert status["status"] == "pending", "an acknowledgement of an older epoch never reads applied"
    finally:
        sched.scheduler.shutdown(wait=False)


async def _hold_share_lock_until(maker, release: asyncio.Event, held: asyncio.Event):
    async with maker() as db:
        await db.execute(text("SELECT id FROM scheduler_owner_leases FOR SHARE"))
        held.set()
        await asyncio.wait_for(release.wait(), 20)
        await db.commit()


async def _remaining_seconds(maker) -> float:
    async with maker() as db:
        return float((await db.execute(text(
            "SELECT EXTRACT(EPOCH FROM (expires_at - (clock_timestamp() AT TIME ZONE 'UTC'))) "
            "FROM scheduler_owner_leases"
        ))).scalar_one())


async def _renew_after_wait_past_expiry(maker):
    async with maker() as db:
        assert await owner_lease.acquire_owner_lease(db, process_id="owner", ttl=timedelta(seconds=2)) == 1
        await db.commit()
    held, release = asyncio.Event(), asyncio.Event()
    holder = asyncio.create_task(_hold_share_lock_until(maker, release, held))
    await asyncio.wait_for(held.wait(), 10)

    async def renew():
        async with maker() as db:
            renewed = await owner_lease.renew_owner_lease(db, process_id="owner", epoch=1, ttl=timedelta(seconds=2))
            await db.commit()
            return renewed

    renewing = asyncio.create_task(renew())
    await _wait_blocked(maker)
    await asyncio.sleep(max(0.0, await _remaining_seconds(maker)) + 0.2)
    release.set()  # the row itself was never modified
    await holder
    assert await renewing is False, "a lease that expired while the renew waited is not extended"


async def _takeover_deadline_after_wait(maker):
    async with maker() as db:
        assert await owner_lease.acquire_owner_lease(db, process_id="old", ttl=timedelta(seconds=1)) == 1
        await db.commit()
    await asyncio.sleep(1.2)
    held, release = asyncio.Event(), asyncio.Event()
    holder = asyncio.create_task(_hold_share_lock_until(maker, release, held))
    await asyncio.wait_for(held.wait(), 10)

    async def take_over():
        async with maker() as db:
            epoch = await owner_lease.acquire_owner_lease(db, process_id="new", ttl=timedelta(seconds=4))
            await db.commit()
            return epoch

    taking = asyncio.create_task(take_over())
    await _wait_blocked(maker)
    await asyncio.sleep(3.0)  # longer than most of the new TTL
    release.set()
    await holder
    assert await taking == 2
    assert await _remaining_seconds(maker) > 3.0, "the deadline is measured when the row is written, after the wait"


test_fenced_takeover_and_stale_acknowledgement = _scenario_test(_fenced_takeover)


test_renew_after_wait_past_expiry = _scenario_test(_renew_after_wait_past_expiry)


test_takeover_deadline_after_wait = _scenario_test(_takeover_deadline_after_wait)
