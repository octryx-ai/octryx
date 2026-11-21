"""Observability → Usage & costs (O3): window, priced coverage, trend, breakdowns, budgets (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth.admin_principal import get_current_admin_user
from ....services.observability.usage_read_model import DEFAULT_WINDOW, usage_overview

router = APIRouter()


@router.get("/usage")
async def get_usage(
    window: str = Query(default=DEFAULT_WINDOW, pattern="^(7d|30d|month)$"),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await usage_overview(db, window=window)
