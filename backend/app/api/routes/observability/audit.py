"""Observability → Audit log (O5): administrative changes only, global admins only; the export is audited."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.audit_trail.timeline import DEFAULT_WINDOW_DAYS, export_audit_csv, list_audit
from ....services.auth.admin_principal import get_current_admin_user

router = APIRouter()


@router.get("/audit")
async def get_audit(
    window_days: int = Query(default=DEFAULT_WINDOW_DAYS, ge=1, le=90),
    category: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1, le=10_000),
    page_size: int = Query(default=50, ge=1, le=100),
    _admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_audit(db, window_days=window_days, category=category, query=q, page=page, page_size=page_size)


@router.post("/audit/export")
async def post_audit_export(
    window_days: int = Query(default=DEFAULT_WINDOW_DAYS, ge=1, le=90),
    category: str | None = Query(default=None, max_length=40),
    q: str | None = Query(default=None, max_length=120),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """A POST, because the export is itself an audited action."""
    body = await export_audit_csv(db, viewer_id=admin.id, window_days=window_days, category=category, query=q)
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'})
