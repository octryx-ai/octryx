"""Import an export package (stored or uploaded) with one audited import log row."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ExportPackage, ImportLog, Project, User
from ..error_facts import error_text
from .core import normalize_import_package_payload, serialize_import_log_row
from .upsert import upsert_agent_from_package, upsert_skill_from_package
from .upsert_task import upsert_task_from_package

UpsertFn = Callable[..., Awaitable[tuple[Any, list[str]]]]
NormalizeFn = Callable[[dict[str, Any]], tuple[str, dict[str, Any], str]]


def _normalize_import_package_payload(package_json: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    return normalize_import_package_payload(package_json)


async def _upsert_skill_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
):
    return await upsert_skill_from_package(
        db,
        current_user=current_user,
        entity=entity,
        overwrite_existing=overwrite_existing,
        name_override=name_override,
    )


async def _upsert_agent_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
):
    return await upsert_agent_from_package(
        db,
        current_user=current_user,
        entity=entity,
        overwrite_existing=overwrite_existing,
        name_override=name_override,
    )


async def _upsert_task_from_package(
    db: AsyncSession,
    *,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
    target_project_id: str | None,
):
    return await upsert_task_from_package(
        db,
        current_user=current_user,
        entity=entity,
        overwrite_existing=overwrite_existing,
        name_override=name_override,
        target_project_id=target_project_id,
    )


async def _target_project_id(db: AsyncSession, target_project_id: str | None) -> str | None:
    normalized_target_project_id = str(target_project_id or "").strip() or None
    if normalized_target_project_id:
        project = await db.get(Project, normalized_target_project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Target project not found")
    return normalized_target_project_id


async def _package_content(
    db: AsyncSession,
    package_id: str | None,
    package_json: dict[str, Any] | None,
    normalize_import_package_payload_func: NormalizeFn,
) -> tuple[ExportPackage | None, str, dict[str, Any], str]:
    row = None
    if package_id:
        row = await db.get(ExportPackage, package_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Export package not found")
        normalized_type = row.package_type
        content_json = row.content_json or {}
        checksum = row.checksum
    else:
        normalized_type, content_json, checksum = normalize_import_package_payload_func(package_json or {})
    return row, normalized_type, content_json, checksum


async def _upsert_entity(
    db: AsyncSession,
    *,
    normalized_type: str,
    current_user: User,
    entity: dict[str, Any],
    overwrite_existing: bool,
    name_override: str | None,
    target_project_id: str | None,
    upsert_skill_from_package_func: UpsertFn,
    upsert_agent_from_package_func: UpsertFn,
    upsert_task_from_package_func: UpsertFn,
) -> tuple[Any, list[str]]:
    if normalized_type in {"skill", "agent"}:
        # Skills and agents are Global; only a task lands in the target Workspace.
        upsert_global = upsert_skill_from_package_func if normalized_type == "skill" else upsert_agent_from_package_func
        return await upsert_global(
            db,
            current_user=current_user,
            entity=entity,
            overwrite_existing=overwrite_existing,
            name_override=name_override,
        )
    return await upsert_task_from_package_func(
        db,
        current_user=current_user,
        entity=entity,
        overwrite_existing=overwrite_existing,
        name_override=name_override,
        target_project_id=target_project_id,
    )


async def _record_failure(db: AsyncSession, log_fields: dict[str, Any], errors: list[str]) -> None:
    await db.rollback()
    db.add(ImportLog(**log_fields, status="failed", errors=errors))
    await db.commit()


def _complete(log_entry: ImportLog, normalized_type: str, imported_entity: Any, warnings: list[str]) -> None:
    log_entry.status = "completed_with_warnings" if warnings else "completed"
    log_entry.errors = warnings
    log_entry.imported_entity_type = normalized_type
    log_entry.imported_entity_id = imported_entity.id
    log_entry.imported_entity_name = getattr(imported_entity, "name", None)


async def import_package(
    db: AsyncSession,
    *,
    current_user: User,
    package_id: str | None = None,
    package_json: dict[str, Any] | None = None,
    overwrite_existing: bool = False,
    target_project_id: str | None = None,
    name_override: str | None = None,
    normalize_import_package_payload_func: NormalizeFn = _normalize_import_package_payload,
    upsert_skill_from_package_func: UpsertFn = _upsert_skill_from_package,
    upsert_agent_from_package_func: UpsertFn = _upsert_agent_from_package,
    upsert_task_from_package_func: UpsertFn = _upsert_task_from_package,
) -> dict[str, Any]:
    normalized_target_project_id = await _target_project_id(db, target_project_id)
    row, normalized_type, content_json, checksum = await _package_content(
        db, package_id, package_json, normalize_import_package_payload_func
    )

    entity = content_json.get("entity")
    if not isinstance(entity, dict):
        raise HTTPException(status_code=400, detail="Package entity payload is invalid")

    # Plain values captured before any rollback: a rollback expires every persisted row the
    # session holds (the actor, a saved package), and reading one afterwards is a lazy load that fails.
    log_id = str(uuid.uuid4())
    log_fields = {
        "id": log_id,
        "package_id": row.id if row else None,
        "package_type": normalized_type,
        "package_checksum": checksum,
        "imported_by": current_user.id,
        "overwrite_existing": overwrite_existing,
        "target_project_id": normalized_target_project_id,
    }
    log_entry = ImportLog(**log_fields, status="running", errors=[])
    db.add(log_entry)
    await db.flush()
    try:
        imported_entity, warnings = await _upsert_entity(
            db,
            normalized_type=normalized_type,
            current_user=current_user,
            entity=entity,
            overwrite_existing=overwrite_existing,
            name_override=name_override,
            target_project_id=normalized_target_project_id,
            upsert_skill_from_package_func=upsert_skill_from_package_func,
            upsert_agent_from_package_func=upsert_agent_from_package_func,
            upsert_task_from_package_func=upsert_task_from_package_func,
        )
        _complete(log_entry, normalized_type, imported_entity, warnings)
        await db.commit()
    except HTTPException as exc:
        await _record_failure(db, log_fields, [str(exc.detail)])
        raise
    except Exception as exc:
        await _record_failure(db, log_fields, [error_text("package_import_failed", exc)])
        raise
    return serialize_import_log_row(await db.get(ImportLog, log_id))
