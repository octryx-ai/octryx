"""Real-PostgreSQL harness for cross-transaction boundaries. Holds no tests by design.

Advisory locks and ``SELECT … FOR UPDATE`` row locks are *cross-transaction* facts: none of them
can be observed on the SQLite harness, and none of them may be asserted by how long something
took. So every module that proves one of them needs the same things, which live here once:

- a disposable PostgreSQL database, already migrated to Alembic head, named by
  ``OCTRYX_TEST_LEDGER_POSTGRES_URL``; without it the tests skip::

      createdb octryx_ledger_test && alembic upgrade head   # against that URL
      export OCTRYX_TEST_LEDGER_POSTGRES_URL=\\
          postgresql+asyncpg://user:pw@127.0.0.1:5432/octryx_ledger_test

- **independent sessions**, one per actor, so concurrent writers really are separate
  transactions on separate connections, as they are in production;
- state read out of PostgreSQL itself (``pg_locks``) and polled with a bound, so a slow machine
  takes longer and a boundary that is not held still fails.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.postgres_env import postgres_url

POSTGRES_URL_ENV = "OCTRYX_TEST_LEDGER_POSTGRES_URL"
requires_postgres = pytest.mark.skipif(
    not postgres_url("LEDGER_POSTGRES_URL"),
    reason=f"set {POSTGRES_URL_ENV} to a disposable PostgreSQL database migrated to head",
)

# Bounded polls, never a sleep an assertion depends on.
POLL_SECONDS = 0.05
POLL_ATTEMPTS = 400

UNGRANTED_ADVISORY = text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
GRANTED_ADVISORY = text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted")
# A writer blocked on a row this slice locked waits on a transaction id, not on an advisory key.
UNGRANTED_ROW_WAIT = text(
    "SELECT count(*) FROM pg_locks WHERE locktype IN ('transactionid', 'tuple') AND NOT granted"
)


def postgres_sessions() -> tuple[object, async_sessionmaker[AsyncSession]]:
    """One engine with no pooling and its session factory: every session its own connection."""
    engine = create_async_engine(postgres_url("LEDGER_POSTGRES_URL"), poolclass=NullPool)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def scalar(session: AsyncSession, statement) -> int:
    """One count read on its own connection, with nothing left open behind it."""
    value = int((await session.execute(statement)).scalar_one())
    await session.rollback()
    return value


async def until(session: AsyncSession, statement, expected: int) -> None:
    """Poll one PostgreSQL count until it is reached, or fail with what it was."""
    seen = 0
    for _ in range(POLL_ATTEMPTS):
        seen = await scalar(session, statement)
        if seen >= expected:
            return
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError(f"PostgreSQL lock state never reached {expected} (last {seen})")
