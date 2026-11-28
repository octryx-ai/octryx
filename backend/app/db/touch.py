"""A "last used / last seen" time that never makes a request wait."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..time_utils import utc_now

DEFAULT_RESOLUTION = timedelta(seconds=60)


async def touch_if_stale(db: AsyncSession, model: Any, row_id: str, current: datetime | None, *,
                         column: str = "last_used_at", resolution: timedelta = DEFAULT_RESOLUTION) -> bool:
    now = utc_now()
    if current is not None and now - current < resolution:
        return False
    field = getattr(model, column)
    free = (select(model.id).where(model.id == row_id, field.is_(None) | (field < now - resolution))
            .with_for_update(skip_locked=True).scalar_subquery())
    result = await db.execute(update(model).where(model.id == free).values({column: now})
                              .execution_options(synchronize_session=False))
    return bool(result.rowcount)
