"""MASH platform registration and heartbeat routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from ....db import get_db
from ..services.platform_service import (
    get_platform_info,
    heartbeat,
    list_platforms,
    register_platform,
)
from .auth import require_mash_token

router = APIRouter(prefix="/mash/v1/platforms", tags=["mash-platforms"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class PlatformRegisterRequest(BaseModel):
    name: str
    description: str | None = None
    platform_type: str = "octryx"
    metadata: dict[str, Any] | None = None
    requested_scopes: list[str] | None = None


class HeartbeatRequest(BaseModel):
    status: str = "online"
    capabilities: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/register")
async def platform_register(
    payload: PlatformRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Register a new platform. Requires admin access or platform:register scope."""
    try:
        result = await register_platform(
            db,
            name=payload.name,
            description=payload.description,
            platform_type=payload.platform_type,
            metadata=payload.metadata,
            requested_scopes=payload.requested_scopes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return JSONResponse(result, status_code=201)


@router.get("/me")
async def platform_me(
    token: dict[str, Any] = Depends(require_mash_token),
    db: AsyncSession = Depends(get_db),
):
    """Return info about the authenticated platform."""
    info = await get_platform_info(db, platform_id=token["sub"])
    if not info:
        raise HTTPException(status_code=404, detail="Platform not found")
    return JSONResponse(info)


@router.put("/me/heartbeat")
async def platform_heartbeat(
    payload: HeartbeatRequest,
    token: dict[str, Any] = Depends(require_mash_token),
    db: AsyncSession = Depends(get_db),
):
    """Update platform heartbeat and optional capability manifest."""
    try:
        result = await heartbeat(
            db,
            platform_id=token["sub"],
            capabilities=payload.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return JSONResponse(result)


@router.get("")
async def platform_list(
    db: AsyncSession = Depends(get_db),
):
    """List all registered platforms (admin view)."""
    return JSONResponse(await list_platforms(db))
