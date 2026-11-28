"""The one clock scheduler coordination compares lease instants against."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import DateTime, func, literal
from sqlalchemy.ext.asyncio import AsyncSession

from ...services.knowledge.ledger.database_clock import database_now
from ...time_utils import utc_now


class SchedulerCoordinationClockError(RuntimeError):
    pass


async def db_now(db: AsyncSession) -> datetime:
    return await database_now(db)


def now_expression(db: AsyncSession):
    name = getattr(getattr(db.get_bind(), "dialect", None), "name", None)
    if name == "postgresql":
        return func.timezone("UTC", func.clock_timestamp())
    if name == "sqlite":
        return literal(utc_now(), DateTime())
    raise SchedulerCoordinationClockError()


def deadline_expression(db: AsyncSession, ttl: timedelta):
    name = getattr(getattr(db.get_bind(), "dialect", None), "name", None)
    if name == "postgresql":
        return func.timezone("UTC", func.clock_timestamp()) + ttl
    if name == "sqlite":
        return literal(utc_now() + ttl, DateTime())
    raise SchedulerCoordinationClockError()

