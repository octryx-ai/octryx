from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.admin.admin_panel._governance import ReportExportCreateRequest

from ....db import get_db
from ....models import User
from ....services.analytics import service as analytics_service
from ....services.analytics.service import (
    create_report_export,
    get_report_export,
    list_analytics_daily,
    list_report_exports,
)
from ....services.auth import get_current_user
from ....services.chargeback import list_monthly_cost_reports
from ....services.notification_delivery import require_admin_user

router = APIRouter(prefix="/api/v1", tags=["analytics"])


def _parse_date(value: str | None, *, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}") from exc


@router.get("/analytics/daily")
async def get_analytics_daily(
    project_id: str | None = None,
    team_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_analytics_daily(
        db,
        project_id=(project_id or "").strip() or None,
        team_id=(team_id or "").strip() or None,
        date_from=_parse_date(date_from, field_name="date_from"),
        date_to=_parse_date(date_to, field_name="date_to"),
        limit=limit,
    )


@router.get("/reports/export")
async def get_report_export_list(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_report_exports(db, limit=limit)


@router.post("/reports/export")
async def post_report_export(
    body: ReportExportCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await create_report_export(
        db,
        current_user=current_user,
        report_type=body.report_type,
        format=body.format,
        parameters=body.parameters,
    )


@router.get("/reports/export/{report_export_id}/download")
async def download_report_export(
    report_export_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    row = await get_report_export(db, report_export_id)
    if row.status != "completed" or not row.file_url:
        raise HTTPException(status_code=409, detail="Report export is not ready")
    file_path = Path(row.file_url).resolve()
    # Restrict the path to allowed export directory to prevent traversal
    allowed_dir = analytics_service.REPORT_EXPORT_DIR.resolve()
    try:
        file_path.relative_to(allowed_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid export file path")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    media_type = "application/json"
    if row.format == "csv":
        media_type = "text/csv"
    elif row.format == "pdf":
        media_type = "application/pdf"
    return FileResponse(str(file_path), media_type=media_type, filename=file_path.name)


@router.get("/reports/cost")
async def get_cost_chargeback_report(
    period: str = Query(..., min_length=7, max_length=7),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_admin_user(db, current_user)
    return await list_monthly_cost_reports(db, period=period)
