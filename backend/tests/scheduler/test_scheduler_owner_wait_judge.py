"""Independent lease acceptance after an actual PostgreSQL row-lock wait."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.scheduler.coordination.owner_lease import acquire_owner_lease, admit_owner
from tests.alembic_model_parity_support import migrated_database, requires_postgres

pytestmark = requires_postgres


async def _expired_while_waiting(url: str) -> bool:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    contender = None
    try:
        async with sessions() as seed:
            epoch = await acquire_owner_lease(seed, process_id="judge-owner", ttl=timedelta(seconds=2))
            await seed.commit()
        assert epoch == 1, "first insert must establish ownership immediately"

        async with sessions() as blocker, sessions() as observer:
            await blocker.execute(text("SELECT id FROM scheduler_owner_leases FOR UPDATE"))
            pid_ready = asyncio.Event()
            contender_pid = None

            async def admission():
                nonlocal contender_pid
                async with sessions() as candidate:
                    contender_pid = (await candidate.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                    pid_ready.set()
                    result = await admit_owner(candidate, process_id="judge-owner", epoch=epoch)
                    await candidate.rollback()
                    return result

            contender = asyncio.create_task(admission())
            await asyncio.wait_for(pid_ready.wait(), 5)
            async with asyncio.timeout(5):
                while True:
                    waiting = (await observer.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": contender_pid}
                    )).scalar_one()
                    if waiting:
                        break
                    assert not contender.done(), "admission must actually wait on the held row lock"
                    await asyncio.sleep(0.01)

            remaining = (await observer.execute(text(
                "SELECT EXTRACT(EPOCH FROM (expires_at - (clock_timestamp() AT TIME ZONE 'UTC'))) "
                "FROM scheduler_owner_leases"
            ))).scalar_one()
            await asyncio.sleep(max(0.0, float(remaining)) + 0.05)
            # No row update: PostgreSQL cannot rely on a changed tuple to re-evaluate the predicate.
            await blocker.commit()
            return await asyncio.wait_for(contender, 5)
    finally:
        if contender is not None and not contender.done():
            contender.cancel()
            await asyncio.gather(contender, return_exceptions=True)
        await engine.dispose()


def test_owner_admission_checks_expiry_after_unchanged_row_lock_wait(tmp_path):
    with migrated_database("postgresql", tmp_path) as database:
        admitted = asyncio.run(_expired_while_waiting(database.url))
    assert admitted is False, "a lease that expired while waiting must not admit a new fire or acknowledgement"


async def _first_insert_after_conflict_rollback(url: str) -> tuple[int | None, bool]:
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    contender = None
    try:
        async with sessions() as blocker, sessions() as observer:
            assert await acquire_owner_lease(blocker, process_id="uncommitted-owner") == 1
            pid_ready = asyncio.Event()
            contender_pid = None

            async def acquire():
                nonlocal contender_pid
                async with sessions() as candidate:
                    contender_pid = (await candidate.execute(text("SELECT pg_backend_pid()"))).scalar_one()
                    pid_ready.set()
                    epoch = await acquire_owner_lease(candidate, process_id="first-surviving-owner",
                                                       ttl=timedelta(seconds=2))
                    live = (await candidate.execute(text(
                        "SELECT expires_at > (clock_timestamp() AT TIME ZONE 'UTC') "
                        "FROM scheduler_owner_leases"
                    ))).scalar_one()
                    await candidate.rollback()
                    return epoch, live

            contender = asyncio.create_task(acquire())
            await asyncio.wait_for(pid_ready.wait(), 5)
            async with asyncio.timeout(5):
                while True:
                    blocked = (await observer.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": contender_pid}
                    )).scalar_one()
                    if blocked:
                        break
                    assert not contender.done(), "singleton INSERT must really wait for the competing transaction"
                    await asyncio.sleep(0.01)
            await asyncio.sleep(2.1)
            # The conflicting INSERT disappears, so this is still the successful epoch-1 INSERT path.
            await blocker.rollback()
            return await asyncio.wait_for(contender, 5)
    finally:
        if contender is not None and not contender.done():
            contender.cancel()
            await asyncio.gather(contender, return_exceptions=True)
        await engine.dispose()


def test_first_successful_insert_owns_a_live_lease_after_conflict_wait(tmp_path):
    with migrated_database("postgresql", tmp_path) as database:
        epoch, live = asyncio.run(_first_insert_after_conflict_rollback(database.url))
    assert epoch == 1
    assert live is True, "successful singleton INSERT must not install a lease that expired during the wait"
