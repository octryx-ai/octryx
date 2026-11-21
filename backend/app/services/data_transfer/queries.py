from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DataExportJob, DataImportJob


def serialize_data_export_job(row: DataExportJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_by": row.created_by,
        "export_type": row.export_type,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "format": row.format,
        "include_sensitive": bool(row.include_sensitive),
        "status": row.status,
        "file_url": row.file_url,
        "file_size_bytes": row.file_size_bytes,
        "summary": row.summary_json or {},
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def serialize_data_import_job(row: DataImportJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_by": row.created_by,
        "import_type": row.import_type,
        "source_format": row.source_format,
        "rows_total": int(row.rows_total or 0),
        "rows_success": int(row.rows_success or 0),
        "rows_failed": int(row.rows_failed or 0),
        "errors": list(row.errors or []),
        "status": row.status,
        "target_project_id": row.target_project_id,
        "summary": row.summary_json or {},
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


async def list_data_export_jobs(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
    export_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(DataExportJob)
    if not is_admin and user_id:
        stmt = stmt.where(DataExportJob.created_by == user_id)
    elif user_id:
        # A person's GDPR export holds their private Workspace; only its creator lists it.
        stmt = stmt.where((DataExportJob.export_type != "user_data_gdpr") | (DataExportJob.created_by == user_id))
    if export_type:
        stmt = stmt.where(DataExportJob.export_type == export_type)
    stmt = stmt.order_by(DataExportJob.created_at.desc()).limit(max(1, min(limit, 100)))
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_data_export_job(row) for row in rows]


async def list_data_import_jobs(
    db: AsyncSession,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
    import_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(DataImportJob).order_by(DataImportJob.created_at.desc()).limit(max(1, min(limit, 100)))
    # Same scoping as the exports: a non-admin sees only their own import jobs.
    if not is_admin:
        stmt = stmt.where(DataImportJob.created_by == user_id)
    if import_type:
        stmt = stmt.where(DataImportJob.import_type == import_type)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_data_import_job(row) for row in rows]


async def get_data_export_job(
    db: AsyncSession, *, job_id: str, user_id: str | None = None, is_admin: bool = False
) -> dict[str, Any]:
    row = await db.get(DataExportJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Data export job not found")
    # User-scoping: only the creator or admin can access the export
    if row.export_type == "user_data_gdpr" and user_id and row.created_by != user_id:
        # Only the creator reads or downloads a GDPR export, admins included.
        raise HTTPException(status_code=404, detail="Data export job not found")
    if not is_admin and user_id and row.created_by != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this export")
    return serialize_data_export_job(row)


async def get_data_import_job(
    db: AsyncSession, *, job_id: str, user_id: str | None = None, is_admin: bool = False
) -> dict[str, Any]:
    row = await db.get(DataImportJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Data import job not found")
    if not is_admin and row.created_by != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this import")
    return serialize_data_import_job(row)
