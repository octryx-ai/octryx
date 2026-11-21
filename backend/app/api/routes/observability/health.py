"""Observability → Health (O4) and Overview (O7): fresh component checks, the roll-up, what needs attention."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import get_settings
from ....db import get_db
from ....models import User
from ....runtime_lifecycle import get_platform_runtime
from ....services.auth.admin_principal import get_current_admin_user
from ....services.observability.health_read_model import health_overview
from ....services.observability.overview_read_model import overview

router = APIRouter()


@router.get("/health")
async def get_health(
    request: Request,
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    runtime = get_platform_runtime(getattr(request.app.state, "async_session_factory", None))
    platform = await runtime.health_checks(app_version=get_settings().app_version)
    return await health_overview(db, checks=dict(platform.get("checks") or {}))


@router.get("/overview")
async def get_overview(
    request: Request,
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    runtime = get_platform_runtime(getattr(request.app.state, "async_session_factory", None))
    platform = await runtime.health_checks(app_version=get_settings().app_version)
    return await overview(db, checks=dict(platform.get("checks") or {}))
