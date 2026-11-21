from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.data_transfer.common import (
    _dump_structured_content,
    _is_admin_user,
    _write_export_file,
)
from app.services.data_transfer.export_payloads import (
    ADMIN_CONFIG_EXCLUDED_SECTIONS,
    ADMIN_CONFIG_INCLUDED_SECTIONS,
    _build_admin_config_backup_payload,
    _build_definition_export_payload,
    _build_project_backup_payload,
)
from app.services.data_transfer.gdpr_export import _build_user_data_gdpr_zip
from app.services.data_transfer.queries import serialize_data_export_job

from ...models import DataExportJob, User
from ...time_utils import utc_now

_EXPORT_TYPES = {"admin_config_backup", "project_backup", "user_data_gdpr", "task_definitions", "agent_definitions"}


async def create_data_export_job(
    db: AsyncSession,
    *,
    current_user: User,
    export_type: str,
    scope_type: str,
    scope_id: str | None,
    format_name: str,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    normalized_type = str(export_type or "").strip().lower()
    normalized_scope_type = str(scope_type or "").strip().lower()
    normalized_scope_id = str(scope_id or "").strip() or None
    normalized_format = await _validated_export_format(
        db, current_user=current_user, normalized_type=normalized_type, normalized_scope_type=normalized_scope_type,
        normalized_scope_id=normalized_scope_id, normalized_format=str(format_name or "").strip().lower(),
    )
    job = DataExportJob(
        id=str(uuid.uuid4()),
        created_by=current_user.id,
        export_type=normalized_type,
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        format=normalized_format,
        include_sensitive=include_sensitive,
        status="running",
    )
    db.add(job)
    await db.flush()

    try:
        content, summary = await _export_content(
            db, current_user=current_user, normalized_type=normalized_type, normalized_scope_type=normalized_scope_type,
            normalized_scope_id=normalized_scope_id, normalized_format=normalized_format,
        )
        file_url, file_size_bytes = _write_export_file(job.id, normalized_type, normalized_format, content)
        job.file_url = file_url
        job.file_size_bytes = file_size_bytes
        job.summary_json = summary
        job.status = "completed"
        job.completed_at = utc_now()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        retry = _failed_export_job(
            job.id, current_user, normalized_type, normalized_scope_type, normalized_scope_id, normalized_format,
            include_sensitive, exc,
        )
        db.add(retry)
        await db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise

    return serialize_data_export_job(await db.get(DataExportJob, job.id))


async def _validated_export_format(
    db: AsyncSession,
    *,
    current_user: User,
    normalized_type: str,
    normalized_scope_type: str,
    normalized_scope_id: str | None,
    normalized_format: str,
) -> str:
    """Refuse an export the caller may not run; the GDPR export is always a zip."""
    if normalized_type not in _EXPORT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported export_type")
    if normalized_scope_type not in {"project", "user", "global"}:
        raise HTTPException(status_code=400, detail="Unsupported scope_type")

    if normalized_type == "user_data_gdpr":
        if normalized_scope_type != "user":
            raise HTTPException(status_code=400, detail="user_data_gdpr requires scope_type=user")
        if normalized_scope_id is None:
            raise HTTPException(status_code=400, detail="scope_id is required")
        if normalized_scope_id != current_user.id and not await _is_admin_user(db, current_user):
            raise HTTPException(status_code=403, detail="Admin access required for exporting other users")
        if normalized_format != "zip":
            normalized_format = "zip"
    elif not await _is_admin_user(db, current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    if normalized_scope_type == "project" and normalized_scope_id:
        from ..project.private_workspace import private_project  # noqa: PLC0415

        if await private_project(db, normalized_scope_id) is not None:  # no admin export of a private one
            raise HTTPException(status_code=404, detail="Project not found")
    return normalized_format


async def _export_content(
    db: AsyncSession,
    *,
    current_user: User,
    normalized_type: str,
    normalized_scope_type: str,
    normalized_scope_id: str | None,
    normalized_format: str,
) -> tuple[Any, dict[str, Any]]:
    if normalized_type == "admin_config_backup":
        if normalized_scope_type != "project" or normalized_scope_id is None:
            raise HTTPException(
                status_code=400, detail="admin_config_backup requires scope_type=project and scope_id"
            )
        payload = await _build_admin_config_backup_payload(db, project_id=normalized_scope_id)
        content = _dump_structured_content(payload, normalized_format)
        summary = {
            "included_sections": list(ADMIN_CONFIG_INCLUDED_SECTIONS),
            "excluded_sections": list(ADMIN_CONFIG_EXCLUDED_SECTIONS),
            "task_count": len(payload["tasks"]),
            "agent_count": len(payload["agents"]),
            "skill_count": len(payload["skills"]),
        }
    elif normalized_type == "project_backup":
        if normalized_scope_type != "project" or normalized_scope_id is None:
            raise HTTPException(status_code=400, detail="project_backup requires scope_type=project and scope_id")
        payload = await _build_project_backup_payload(db, project_id=normalized_scope_id)
        content = _dump_structured_content(payload, normalized_format)
        summary = {
            "task_count": len(payload["tasks"]),
            "agent_count": len(payload["agents"]),
            "skill_count": len(payload["skills"]),
        }
    elif normalized_type == "user_data_gdpr":
        content = await _build_user_data_gdpr_zip(db, user_id=normalized_scope_id or "",
                                                  requester_id=str(current_user.id))
        summary = {"user_id": normalized_scope_id}
    else:
        project_id = normalized_scope_id if normalized_scope_type == "project" else None
        payload = await _build_definition_export_payload(db, export_type=normalized_type, project_id=project_id)
        content = _dump_structured_content(payload, normalized_format)
        summary = {"count": len(payload.get("tasks") or payload.get("agents") or [])}
    return content, summary


def _failed_export_job(
    job_id: str,
    current_user: User,
    normalized_type: str,
    normalized_scope_type: str,
    normalized_scope_id: str | None,
    normalized_format: str,
    include_sensitive: bool,
    exc: Exception,
) -> DataExportJob:
    return DataExportJob(
        id=job_id,
        created_by=current_user.id,
        export_type=normalized_type,
        scope_type=normalized_scope_type,
        scope_id=normalized_scope_id,
        format=normalized_format,
        include_sensitive=include_sensitive,
        status="failed",
        error=str(getattr(exc, "detail", exc)),
        summary_json={},
        completed_at=utc_now(),
    )


# The public names of this module (other modules import them).
__all__ = [
    "create_data_export_job",
]
