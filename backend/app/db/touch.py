"""A "last used / last seen" time that never makes a request wait.

Such a time is a hint, not a ledger. Written on every request inside the request's transaction, it held the row's
lock for the whole request: parallel requests with one credential queued on it, filled the connection pool, and the
lock holder then waited for a connection of its own (deadlock, every keyed request 500).

``touch_if_stale`` writes the time at most once per ``resolution`` and only when the row is free: a row another
transaction holds is skipped (``FOR UPDATE SKIP LOCKED``), so no request ever waits on it. It opens no second
connection (that is the other half of the deadlock) and leaves the loaded ORM object unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..time_utils import utc_now

DEFAULT_RESOLUTION = timedelta(seconds=60)


async def touch_if_stale(db: AsyncSession, model: Any, row_id: str, current: datetime | None, *,
                         column: str = "last_used_at", resolution: timedelta = DEFAULT_RESOLUTION) -> bool:
    """Set ``model.<column>`` of ``row_id`` to now when it is older than ``resolution``; True when it was written."""
    now = utc_now()
    if current is not None and now - current < resolution:
        return False
    field = getattr(model, column)
    free = (select(model.id).where(model.id == row_id, field.is_(None) | (field < now - resolution))
            .with_for_update(skip_locked=True).scalar_subquery())
    result = await db.execute(update(model).where(model.id == free).values({column: now})
                              .execution_options(synchronize_session=False))
    return bool(result.rowcount)
