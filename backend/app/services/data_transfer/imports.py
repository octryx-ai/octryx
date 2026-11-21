from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_transfer.common import _is_admin_user, _parse_source_payload
from app.services.data_transfer.import_rows import (
    _import_agent_rows,
    _import_skill_rows,
    _import_task_rows,
    _import_user_rows,
)
from app.services.data_transfer.queries import serialize_data_import_job

from ...models import DataImportJob, Project, User
from ...time_utils import utc_now
from .import_backup import _import_admin_config_backup

_IMPORT_TYPES = {"admin_config_backup", "tasks", "users", "skills", "agent_definitions"}
_PROJECT_SCOPED_IMPORT_TYPES = {"admin_config_backup", "tasks", "agent_definitions"}


async def create_data_import_job(
    db: AsyncSession,
    *,
    current_user: User,
    import_type: str,
    source_format: str,
    payload_json: Any | None,
    payload_text: str | None,
    target_project_id: str | None,
    overwrite_existing: bool = False,
    restore_sections: list[str] | None = None,
    overwrite_skills: bool = False,
) -> dict[str, Any]:
    normalized_type, normalized_target_project_id = await _validated_import_request(
        db, current_user=current_user, import_type=import_type, target_project_id=target_project_id
    )
    payload = _parse_source_payload(source_format, payload_json, payload_text)
    job = DataImportJob(
        id=str(uuid.uuid4()),
        created_by=current_user.id,
        import_type=normalized_type,
        source_format=str(source_format or "").strip().lower(),
        target_project_id=normalized_target_project_id,
        status="running",
    )
    db.add(job)
    await db.flush()
    try:
        rows_total, rows_success, rows_failed, errors, summary = await _run_import(
            db,
            current_user=current_user,
            normalized_type=normalized_type,
            payload=payload,
            target_project_id=normalized_target_project_id or "",
            overwrite_existing=overwrite_existing,
            restore_sections=restore_sections,
            overwrite_skills=overwrite_skills,
        )
        job.rows_total = rows_total
        job.rows_success = rows_success
        job.rows_failed = rows_failed
        job.errors = errors
        job.summary_json = summary
        job.status = "completed_with_warnings" if errors else "completed"
        job.completed_at = utc_now()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        retry = _failed_import_job(
            job.id, current_user, normalized_type, source_format, normalized_target_project_id, exc
        )
        db.add(retry)
        await db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise

    return serialize_data_import_job(await db.get(DataImportJob, job.id))


async def _validated_import_request(
    db: AsyncSession, *, current_user: User, import_type: str, target_project_id: str | None
) -> tuple[str, str | None]:
    if not await _is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    normalized_type = str(import_type or "").strip().lower()
    if normalized_type not in _IMPORT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported import_type")
    normalized_target_project_id = str(target_project_id or "").strip() or None
    if normalized_type in _PROJECT_SCOPED_IMPORT_TYPES and not normalized_target_project_id:
        raise HTTPException(status_code=400, detail="target_project_id is required")
    if normalized_target_project_id:
        project = await db.get(Project, normalized_target_project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Target project not found")
    return normalized_type, normalized_target_project_id


async def _run_import(
    db: AsyncSession,
    *,
    current_user: User,
    normalized_type: str,
    payload: Any,
    target_project_id: str,
    overwrite_existing: bool,
    restore_sections: list[str] | None,
    overwrite_skills: bool,
) -> tuple[int, int, int, list[str], dict[str, Any]]:
    if normalized_type == "admin_config_backup":
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Admin config backup import payload must be an object")
        return await _import_admin_config_backup(
            db,
            current_user=current_user,
            payload=payload,
            target_project_id=target_project_id,
            overwrite_existing=overwrite_existing,
            restore_sections=restore_sections,
            overwrite_skills=overwrite_skills,
        )
    if normalized_type == "users":
        rows = _payload_rows(payload, "users", "Users import payload must be a list")
        rows_success, rows_failed, errors = await _import_user_rows(
            db, rows=rows, overwrite_existing=overwrite_existing
        )
        return len(rows), rows_success, rows_failed, errors, {"user_count": rows_success}
    if normalized_type == "skills":
        rows = _payload_rows(payload, "skills", "Skills import payload must be a list")
        rows_success, rows_failed, errors = await _import_skill_rows(
            db, current_user=current_user, rows=rows, overwrite_existing=overwrite_existing
        )
        return len(rows), rows_success, rows_failed, errors, {"skill_count": rows_success}
    if normalized_type == "tasks":
        rows = _payload_rows(payload, "tasks", "Tasks import payload must be a list or definitions export payload")
        importer, count_key = _import_task_rows, "task_count"
    else:
        rows = _payload_rows(payload, "agents", "Agent import payload must be a list or definitions export payload")
        importer, count_key = _import_agent_rows, "agent_count"
    rows_success, rows_failed, errors = await importer(
        db,
        current_user=current_user,
        rows=rows,
        target_project_id=target_project_id,
        overwrite_existing=overwrite_existing,
    )
    return len(rows), rows_success, rows_failed, errors, {count_key: rows_success}


def _payload_rows(payload: Any, key: str, error_detail: str) -> list[Any]:
    rows = payload.get(key) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise HTTPException(status_code=400, detail=error_detail)
    return rows


def _failed_import_job(
    job_id: str,
    current_user: User,
    normalized_type: str,
    source_format: str,
    target_project_id: str | None,
    exc: Exception,
) -> DataImportJob:
    return DataImportJob(
        id=job_id,
        created_by=current_user.id,
        import_type=normalized_type,
        source_format=str(source_format or "").strip().lower(),
        target_project_id=target_project_id,
        status="failed",
        errors=[str(getattr(exc, "detail", exc))],
        rows_total=0,
        rows_success=0,
        rows_failed=0,
        completed_at=utc_now(),
        summary_json={},
    )


# The public names of this module (other modules and tests import them).
__all__ = [
    "create_data_import_job",
]
