"""Real PostgreSQL: 17 deferred repository steps never starve the pool.

Each "step" does what ``deferred_action.execute`` does around ``scm.create_branch``: a short claim transaction, then a
free executor slot (waited for without a session), then one transaction that waits on the real cache clone lock of
its own session workspace and on a real subprocess longer than the pool timeout. 17 in one process, a pool of 15 like
the API's 5 + 10: no step and no other request gets a QueuePool timeout, at most ``max_concurrent()`` connections are
held by steps at once (a third of the pool, counted around each step's transaction), and every claim (the request's part) takes well under 2 s. The control without the slots shows
the incident. Needs ``OCTRYX_TEST_POSTGRES_URL``; it only reads (``SELECT 1``).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import nullcontext
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.services.workflow_runs import deferred_action
from app.tools.connectors.cloud_common import _run_subprocess_once
from app.tools.connectors.scm_cache_clone import cache_clone_lock
from tests.alembic_model_parity_support import postgres_url, requires_postgres

STEPS = 17
POOL_TIMEOUT = 1.0
STEP_SECONDS = 1.2  # the git part of one step: longer than the pool timeout


async def _scenario(url: str, root: Path, *, slots: bool = True) -> tuple[list[str], int, float]:
    # 15 connections like the API's 5 + 10, opened beforehand: 17 new connections at once spend about 2 s of the
    # event loop on their password handshake.
    engine = create_async_engine(url, pool_size=15, max_overflow=0, pool_timeout=POOL_TIMEOUT)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    errors: list[str] = []
    claim_seconds: list[float] = []
    held = most_held = 0
    # The control lines all steps up before their transaction, so the 2 steps beyond the pool wait for a connection
    # while 15 hold theirs for STEP_SECONDS > POOL_TIMEOUT: the timeout follows from the numbers, not from how fast the
    # claims happen to run on a loaded machine.
    together = None if slots else asyncio.Barrier(STEPS)

    async def warm() -> None:
        async with factory() as db:
            await db.execute(text("SELECT 1"))
            await asyncio.sleep(0.2)

    await asyncio.gather(*(warm() for _ in range(15)))

    async def step(number: int) -> None:
        nonlocal held, most_held
        try:
            started = time.monotonic()
            async with factory() as db:  # 1. the claim (in the product: the request's own transaction)
                await db.execute(text("SELECT 1"))
                await db.commit()
            claim_seconds.append(time.monotonic() - started)
            if together is not None:
                await together.wait()
            async with deferred_action.executor_slots() if slots else nullcontext():  # 2. no session while waiting
                async with factory() as db:  # 3. the step: one transaction
                    await db.execute(text("SELECT 1"))  # the connection is checked out from here to the commit
                    held += 1
                    most_held = max(most_held, held)
                    try:
                        async with cache_clone_lock(root / f"session-{number}" / "github" / "acme" / "payments"):
                            code, _, _ = await _run_subprocess_once(["sleep", str(STEP_SECONDS)])
                            assert code == 0
                    finally:
                        held -= 1
                    await db.commit()
        except Exception as error:  # noqa: BLE001 - counted, the test asserts on the list
            errors.append(f"step: {type(error).__name__}")

    async def other_request() -> None:  # e.g. the Work page while the steps run
        await asyncio.sleep(0.5)
        try:
            async with factory() as db:
                await db.execute(text("SELECT 1"))
        except Exception as error:  # noqa: BLE001
            errors.append(f"other request: {type(error).__name__}")

    try:
        await asyncio.wait_for(asyncio.gather(other_request(), *(step(n) for n in range(STEPS))), timeout=90)
    finally:
        await engine.dispose()
    return errors, most_held, max(claim_seconds or [0.0])


@requires_postgres
def test_seventeen_deferred_steps_leave_the_pool_to_requests(tmp_path: Path) -> None:
    errors, most_held, slowest_claim = asyncio.run(_scenario(postgres_url(), tmp_path / "workspaces"))
    assert errors == []
    assert most_held <= deferred_action.max_concurrent()
    assert slowest_claim < 2.0


@requires_postgres
def test_control_without_the_slots_starves_the_pool(tmp_path: Path) -> None:
    errors, most_held, _ = asyncio.run(_scenario(postgres_url(), tmp_path / "workspaces", slots=False))
    assert any(error.endswith("TimeoutError") for error in errors)  # the incident: a QueuePool timeout
    assert most_held > deferred_action.max_concurrent()
