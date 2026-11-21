"""PostgreSQL proof of the scheduler locking and fencing contract (Alembic-built scratch database).

Each probe observes the blocking with ``pg_blocking_pids`` instead of trusting a compiled clause:

- pause wins: a pause that holds the Scheduler row makes the guarded fire wait, then skip;
- fire wins: a fire that locked the row first commits its run while the pause waits; later fires skip;
- delete and Task pause serialize the same way;
- the first singleton insert owns at once; concurrent first acquires produce exactly one owner;
- an admitted fire holds the lease row FOR SHARE: a takeover after expiry waits until that fire
  commits (expiry does not cancel it); afterwards the old owner's fire and acknowledgement are refused
  and its acknowledgements never read as applied;
- decisions are made after the lease lock is held: a renew that waited past expiry on an unchanged
  row is refused, and a takeover that waited installs a deadline measured after the wait.

No dispatcher, agent or external call runs: fires only insert TaskRun and queue rows.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.scheduler.coordination import owner_lease
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


async def _pause_wins(maker):
    task_id, row_id, fp = await _seed(maker)
    sched = await _owner(maker)
    try:
        async with maker() as pause:
            await pause.execute(text("UPDATE schedulers SET is_active = false WHERE id = :id"), {"id": row_id})
            fire = asyncio.create_task(sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id))
            await _wait_blocked(maker)
            await pause.commit()
        assert await fire is None
        assert await _runs(maker, task_id) == 0
    finally:
        sched.scheduler.shutdown(wait=False)


async def _fire_wins(maker):
    task_id, row_id, fp = await _seed(maker)
    sched = await _owner(maker)
    entered, release = _with_barrier(sched)
    try:
        fire = asyncio.create_task(sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id))
        await asyncio.wait_for(entered.wait(), 15)

        async def pause():
            async with maker() as db:
                await db.execute(text("UPDATE schedulers SET is_active = false WHERE id = :id"), {"id": row_id})
                await db.commit()

        pausing = asyncio.create_task(pause())
        await _wait_blocked(maker)
        assert not pausing.done(), "the pause waits for the admitted fire"
        release.set()
        assert (await fire)["status"] == "queued"
        await pausing
        assert await _runs(maker, task_id) == 1, "the run that won the lock is kept, not cancelled"
        sched._insert_task_run = type(sched)._insert_task_run.__get__(sched)
        assert await sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id) is None
        assert await _runs(maker, task_id) == 1
    finally:
        sched.scheduler.shutdown(wait=False)


async def _delete_and_task_pause(maker):
    task_id, row_id, fp = await _seed(maker)
    sched = await _owner(maker)
    try:
        async with maker() as change:
            await change.execute(text("UPDATE tasks SET is_active = false WHERE id = :id"), {"id": task_id})
            fire = asyncio.create_task(sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id))
            await _wait_blocked(maker)
            await change.commit()
        assert await fire is None, "a Task pause serializes through the FOR SHARE lock"
        async with maker() as change:
            await change.execute(text("UPDATE tasks SET is_active = true WHERE id = :id"), {"id": task_id})
            await change.commit()
        async with maker() as change:
            await change.execute(text("DELETE FROM schedulers WHERE id = :id"), {"id": row_id})
            fire = asyncio.create_task(sched._fire_scheduled("scheduler", fp, task_id, "scheduler", row_id))
            await _wait_blocked(maker)
            await change.commit()
        assert await fire is None
        assert await _runs(maker, task_id) == 0
    finally:
        sched.scheduler.shutdown(wait=False)


async def _concurrent_first_acquire(maker):
    async def acquire(process_id):
        async with maker() as db:
            epoch = await owner_lease.acquire_owner_lease(db, process_id=process_id)
            await db.commit()
            return epoch

    results = await asyncio.gather(acquire("first"), acquire("second"))
    assert sorted(results, key=lambda value: value is None) == [1, None]


test_pause_wins = _scenario_test(_pause_wins)


test_fire_wins = _scenario_test(_fire_wins)


test_delete_and_task_pause_serialize = _scenario_test(_delete_and_task_pause)


test_concurrent_first_acquire = _scenario_test(_concurrent_first_acquire)
