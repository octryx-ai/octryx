"""The one clock scheduler coordination compares lease instants against.

PostgreSQL: ``timezone('UTC', clock_timestamp())``. ``now()`` / ``CURRENT_TIMESTAMP`` are not used:
they are the transaction start instant. A WHERE clause evaluated before a row-lock wait is *not*
re-evaluated when the row it waited for was not modified, so ownership decisions are never made by
a predicate in the locking statement: the lease row is locked first and then read again with a
fresh clock in a separate statement of the same transaction (see ``owner_lease``). Deadlines that
are written use :func:`deadline_expression`, evaluated when the row is written, after any wait.

SQLite is only the test database and an in-process library: there the process clock *is* the
database clock (see ``knowledge/ledger/database_clock.py``), bound as a parameter. SQLite has no
row locks either, so on SQLite these predicates prove decision logic, not lock serialization.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import DateTime, func, literal
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.knowledge.ledger.database_clock import database_now
from ...time_utils import utc_now


class SchedulerCoordinationClockError(RuntimeError):
    """The session's database has no clock this module can name."""


async def db_now(db: AsyncSession) -> datetime:
    """Naive UTC from the database clock (see module docstring)."""
    return await database_now(db)


def now_expression(db: AsyncSession):
    """The database clock as an in-statement expression, re-evaluated after lock waits."""
    name = getattr(getattr(db.get_bind(), "dialect", None), "name", None)
    if name == "postgresql":
        return func.timezone("UTC", func.clock_timestamp())
    if name == "sqlite":
        return literal(utc_now(), DateTime())
    raise SchedulerCoordinationClockError()


def deadline_expression(db: AsyncSession, ttl: timedelta):
    """``now + ttl`` evaluated when the row is written (after any lock wait), not before."""
    name = getattr(getattr(db.get_bind(), "dialect", None), "name", None)
    if name == "postgresql":
        return func.timezone("UTC", func.clock_timestamp()) + ttl
    if name == "sqlite":
        return literal(utc_now() + ttl, DateTime())
    raise SchedulerCoordinationClockError()

