"""Admin-panel service helpers for small panel utility blocks."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...coding_discipline_service import coding_discipline_stats


async def coding_quality_stats(
    db: AsyncSession,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
    project_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    return await coding_discipline_stats(
        db,
        date_from=date_from,
        date_to=date_to,
        project_id=project_id,
        limit=limit,
    )


__all__ = ["coding_quality_stats"]
