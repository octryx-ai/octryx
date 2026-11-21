"""Data exports and imports. Jobs are scoped to their creator unless the caller is a
platform admin; ``GET /backups/history`` lists Workspace backups and restores for platform admins.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...models import User
from ...schemas.comms.data_transfer import DataExportJobCreateRequest, DataImportJobCreateRequest
from ...services.access_control import require_visible_workspace
from ...services.admin.governance.admin_access_service import is_global_admin
from ...services.auth import get_current_user
from ...services.data_transfer import (
    create_data_export_job,
    create_data_import_job,
    get_data_export_job,
    get_data_import_job,
    list_data_export_jobs,
    list_data_import_jobs,
)
from ...services.data_transfer.backup import backup_history

router = APIRouter(prefix="/api/v1/data", tags=["data-transfer"])


@router.get("/exports")
async def api_list_data_exports(
    export_type: str | None = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_data_export_jobs(
        db,
        user_id=current_user.id,
        is_admin=await is_global_admin(db, current_user.id),
        export_type=export_type,
        limit=limit,
    )


@router.post("/exports")
async def api_create_data_export(
    body: DataExportJobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_data_export_job(
        db,
        current_user=current_user,
        export_type=body.export_type,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        format_name=body.format,
        include_sensitive=body.include_sensitive,
    )


@router.get("/exports/{job_id}")
async def api_get_data_export(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_data_export_job(
        db, job_id=job_id, user_id=current_user.id, is_admin=await is_global_admin(db, current_user.id)
    )


@router.get("/exports/{job_id}/download")
async def api_download_data_export(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_data_export_job(
        db, job_id=job_id, user_id=current_user.id, is_admin=await is_global_admin(db, current_user.id)
    )
    if not row.get("file_url"):
        raise HTTPException(status_code=404, detail="Export file not available")
    return FileResponse(row["file_url"], filename=row["file_url"].split("/")[-1])


@router.get("/imports")
async def api_list_data_imports(
    import_type: str | None = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_data_import_jobs(
        db,
        user_id=current_user.id,
        is_admin=await is_global_admin(db, current_user.id),
        import_type=import_type,
        limit=limit,
    )


@router.post("/imports")
async def api_create_data_import(
    body: DataImportJobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_visible_workspace(db, current_user.id, body.target_project_id)
    return await create_data_import_job(
        db,
        current_user=current_user,
        import_type=body.import_type,
        source_format=body.source_format,
        payload_json=body.payload_json,
        payload_text=body.payload_text,
        target_project_id=body.target_project_id,
        overwrite_existing=body.overwrite_existing,
        restore_sections=body.restore_sections,
        overwrite_skills=body.overwrite_skills,
    )


@router.get("/imports/{job_id}")
async def api_get_data_import(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_data_import_job(
        db, job_id=job_id, user_id=current_user.id, is_admin=await is_global_admin(db, current_user.id)
    )


@router.get("/backups/history")
async def api_backup_history(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=403, detail="Admin access required")
    return await backup_history(db, limit=limit)
