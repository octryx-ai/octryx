"""Observability → Runs: list, drawer and the audited content read. Global admins only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.auth.admin_principal import get_current_admin_user
from ....services.observability.run_detail import get_run_detail, read_run_content
from ....services.observability.runs_read_model import DEFAULT_WINDOW_HOURS, list_runs

router = APIRouter()


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


@router.get("/runs")
async def get_runs(
    window_hours: int = Query(default=DEFAULT_WINDOW_HOURS, ge=1, le=168),
    workspace_id: str | None = None,
    source: str | None = None,
    outcome: str | None = None,
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_runs(
        db, window_hours=window_hours, project_id=_clean(workspace_id), source=_clean(source),
        outcome=_clean(outcome), query=_clean(q), page=page, page_size=page_size,
    )


@router.get("/runs/detail")
async def get_run(
    run_key: str = Query(min_length=1, max_length=120),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    payload = await get_run_detail(db, run_key)
    if payload is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    # Chat state is owner-only: the drawer links the session only for its owner.
    return {**payload, "viewer_is_owner": bool(payload.get("user_id")) and payload["user_id"] == admin.id}


@router.post("/runs/content")
async def post_run_content(
    request: Request,
    run_key: str = Query(min_length=1, max_length=120),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Shows the stored content of a run's newest step. A POST, because the read itself is audited."""
    payload = await read_run_content(
        db, run_key, viewer_id=admin.id, ip_address=request.client.host if request.client else None,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return payload
