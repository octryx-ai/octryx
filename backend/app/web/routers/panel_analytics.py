"""Auto-extracted router module: panel_analytics."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas.admin.admin_panel._governance import (
    ExportPackageCreateRequest,
    ImportPackageCreateRequest,
    ReportExportCreateRequest,
)
from app.services.analytics.service import (
    create_report_export,
    get_report_export,
    list_analytics_daily,
    list_report_exports,
)
from app.services.chargeback import (
    list_monthly_cost_reports,
    parse_report_period,
)
from app.services.export_package import (
    create_export_package,
    get_export_package,
    import_package,
    list_export_packages,
    list_import_logs,
)
from app.web._helpers.api_guards import _require_admin_api
from app.web._helpers.panel_serializers import _parse_optional_iso_date

from ...services.access_control import require_existing_workspace

router = APIRouter()


@router.get("/chat/api/panel/analytics/daily")
async def panel_get_analytics_daily(
    request: Request,
    project_id: str | None = None,
    team_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(
        await list_analytics_daily(
            db,
            project_id=(project_id or "").strip() or None,
            team_id=(team_id or "").strip() or None,
            date_from=_parse_optional_iso_date(date_from, field_name="date_from"),
            date_to=_parse_optional_iso_date(date_to, field_name="date_to"),
            limit=limit,
        )
    )


@router.get("/chat/api/panel/reports/cost")
async def panel_get_cost_reports(
    request: Request,
    period: str,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    parse_report_period(period)
    return JSONResponse(await list_monthly_cost_reports(db, period=period))


@router.get("/chat/api/panel/export-packages")
async def panel_get_export_packages(
    request: Request,
    package_type: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await list_export_packages(db, package_type=(package_type or "").strip() or None, limit=limit))


@router.post("/chat/api/panel/export-packages")
async def panel_post_export_package(
    request: Request,
    payload: ExportPackageCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    return JSONResponse(
        await create_export_package(
            db,
            current_user=current_user,
            package_type=payload.package_type,
            entity_id=payload.entity_id,
        )
    )


@router.get("/chat/api/panel/export-packages/{package_id}")
async def panel_get_export_package(
    request: Request,
    package_id: str,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await get_export_package(db, package_id=package_id))


@router.get("/chat/api/panel/import-log")
async def panel_get_import_logs(
    request: Request,
    package_type: str | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await list_import_logs(db, package_type=(package_type or "").strip() or None, limit=limit))


@router.post("/chat/api/panel/import-packages")
async def panel_post_import_package(
    request: Request,
    payload: ImportPackageCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    await require_existing_workspace(db, payload.target_project_id)
    return JSONResponse(
        await import_package(
            db,
            current_user=current_user,
            package_id=payload.package_id,
            package_json=payload.package_json,
            overwrite_existing=payload.overwrite_existing,
            target_project_id=(payload.target_project_id or "").strip() or None,
            name_override=(payload.name_override or "").strip() or None,
        )
    )


@router.get("/chat/api/panel/report-exports")
async def panel_get_report_exports(
    request: Request,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    return JSONResponse(await list_report_exports(db, limit=limit))


@router.post("/chat/api/panel/reports/export")
async def panel_post_report_export(
    request: Request,
    payload: ReportExportCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    current_user = await _require_admin_api(request, db)
    return JSONResponse(
        await create_report_export(
            db,
            current_user=current_user,
            report_type=payload.report_type,
            format=payload.format,
            parameters=payload.parameters,
        )
    )


@router.get("/chat/api/panel/report-exports/{report_export_id}/download")
async def panel_download_report_export(
    report_export_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    await _require_admin_api(request, db)
    row = await get_report_export(db, report_export_id)
    if row.status != "completed" or not row.file_url:
        raise HTTPException(status_code=409, detail="Report export is not ready")
    file_path = Path(row.file_url)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    media_type = "application/json"
    if row.format == "csv":
        media_type = "text/csv"
    elif row.format == "pdf":
        media_type = "application/pdf"
    return FileResponse(str(file_path), media_type=media_type, filename=file_path.name)
