"""The one clock a cross-process lease deadline may be measured against: the database's. SQLite (tests only) is the
process clock; any other dialect fails closed."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from .errors import EvidenceLedgerContractError

# Naive UTC, converted at the server; ``clock_timestamp()``, because ``now()`` answers the transaction start.
_POSTGRESQL_CLOCK = text("SELECT clock_timestamp() AT TIME ZONE 'UTC'")

POSTGRESQL_DIALECT = "postgresql"
# Not a fallback: SQLite is in-process, so its clock and this process's clock are the same clock.
SQLITE_DIALECT = "sqlite"


async def database_now(db: AsyncSession) -> datetime:
    # Replicas can disagree on expiry, so the clock is the one of the database that owns the deadline.
    dialect = _dialect_name(db)
    if dialect == POSTGRESQL_DIALECT:
        reading = (await db.execute(_POSTGRESQL_CLOCK)).scalar_one()
        # Any other value type would silently change what every deadline comparison means.
        if type(reading) is not datetime or reading.tzinfo is not None:
            raise EvidenceLedgerContractError()
        return reading
    if dialect == SQLITE_DIALECT:
        return utc_now()
    raise EvidenceLedgerContractError()


def _dialect_name(db: AsyncSession) -> str:
    dialect = getattr(db.get_bind(), "dialect", None)
    name = getattr(dialect, "name", None)
    if type(name) is not str or not name:
        raise EvidenceLedgerContractError()
    return name
