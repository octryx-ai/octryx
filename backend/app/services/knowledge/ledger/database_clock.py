"""The one clock a cross-process lease deadline may be measured against.

A lease is an agreement between processes about an *instant*: one process installs
``claimed_until`` and every other process decides from it whether the window is still
owned. If each of them answers "now" from its own system clock, that agreement is only
as good as the skew between those clocks — and skew between application replicas is
normal, not exceptional. It is also not a latency problem but a correctness hole: a
process whose clock runs ahead sees a live window as expired, takes it over, and does the
work the current owner is still doing, so the deadline arithmetic is not allowed to depend
on process clocks.

So every instant the lease compares — the claim, the takeover predicate, the renewed
deadline, the fencing predicate, and the remaining time a call may be awaited for — is
read from the database that stores the row. One clock, shared by definition with every
process that can reach the row, so "expired" means the same thing everywhere.

PostgreSQL. ``clock_timestamp()``, deliberately not ``now()``/``CURRENT_TIMESTAMP``:
those answer the *transaction start* time and would report the same instant for the
whole transaction, which is the one thing a deadline check must not do. The reading is
converted at the server (``AT TIME ZONE 'UTC'``) so it arrives as the naive UTC the
``DateTime`` columns hold, rather than being re-based in this process.

SQLite — the one compatibility contract, and it is an identity, not a fallback. SQLite
is only ever the test database here, and it is an in-process library rather than a
server: the process asking for the time *is* the database host, and there is no second
process to be skewed against. The process clock is therefore not an approximation of
the database clock on SQLite, it is the same clock, which is why this is stated as a
contract and pinned by a test instead of being left as a silent default.
``CURRENT_TIMESTAMP`` is specifically *not* used: SQLite renders it at whole-second
granularity, which would coarsen every deadline comparison for no gain.

Any other dialect fails closed. An unrecognised backend is precisely the case where
this module cannot say whose clock it is reading, and a lease whose clock is unknown is
not a lease.

Residual assumption, stated rather than hidden: a bound handed to ``asyncio.timeout``
is a *duration*, and durations are always measured by the local event loop. Reading the
database clock immediately before each call is what keeps that local measurement short
— a single call, not a whole window — so what remains is an assumption about clock
*rate* over seconds, never about the absolute offset between two machines.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ....time_utils import utc_now
from .errors import EvidenceLedgerContractError

# Naive UTC, converted at the server: see the module docstring for why it is
# ``clock_timestamp()`` and not ``now()``.
_POSTGRESQL_CLOCK = text("SELECT clock_timestamp() AT TIME ZONE 'UTC'")

POSTGRESQL_DIALECT = "postgresql"
# The named exception, not a default: SQLite is in-process, so its host clock and this
# process's clock are the same clock.
SQLITE_DIALECT = "sqlite"


async def database_now(db: AsyncSession) -> datetime:
    """Read the current instant from the database that stores the deadlines.

    The reading happens in ``db``'s current transaction, so a caller that compares it
    against a row in the same transaction compares two values of one clock. A caller
    that is about to await an external dependency must not leave that transaction open
    across the call — see :class:`SchemaActivationWindow`, which ends it before the
    call it bounds.
    """
    dialect = _dialect_name(db)
    if dialect == POSTGRESQL_DIALECT:
        reading = (await db.execute(_POSTGRESQL_CLOCK)).scalar_one()
        # A driver that answered an aware value, a string, or ``None`` would silently
        # change what every deadline comparison means.
        if type(reading) is not datetime or reading.tzinfo is not None:
            raise EvidenceLedgerContractError()
        return reading
    if dialect == SQLITE_DIALECT:
        return utc_now()
    raise EvidenceLedgerContractError()


def _dialect_name(db: AsyncSession) -> str:
    """The dialect of the session's bind, or fail closed if it cannot be established."""
    dialect = getattr(db.get_bind(), "dialect", None)
    name = getattr(dialect, "name", None)
    if type(name) is not str or not name:
        raise EvidenceLedgerContractError()
    return name
