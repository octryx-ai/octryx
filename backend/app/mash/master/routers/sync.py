"""MASH incremental sync route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import JSONResponse

from ....db import get_db
from ..services.changelog_service import get_changes_since
from .auth import require_mash_token

router = APIRouter(prefix="/mash/v1/sync", tags=["mash-sync"])


@router.get("/changes")
async def sync_changes(
    since_sequence: int = Query(0, ge=0),
    resource_type: str = Query("all"),
    limit: int = Query(100, ge=1, le=1000),
    token: dict[str, Any] = Depends(require_mash_token),
    db: AsyncSession = Depends(get_db),
):
    """Return changes since a given sequence number."""
    result = await get_changes_since(
        db,
        since_sequence=since_sequence,
        resource_type=resource_type if resource_type != "all" else None,
        limit=limit,
    )
    return JSONResponse(result)
