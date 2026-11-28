"""Workspace backup & restore: the history and the platform-wide skills."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import DataExportJob, DataImportJob, Project, Skill, User
from ..error_facts import error_text
from ..export_package import _upsert_skill_from_package

BACKUP_TYPE = "admin_config_backup"


async def restore_skill_rows(
    db: AsyncSession, *, current_user: User, rows: list[Any], overwrite_skills: bool
) -> tuple[int, int, list[str], dict[str, list[str]]]:
    outcome: dict[str, list[str]] = {"skills_created": [], "skills_kept": [], "skills_overwritten": []}
    errors: list[str] = []
    success = failed = 0
    for index, row in enumerate(rows, start=1):
        entity = row.get("entity") if isinstance(row, dict) and isinstance(row.get("entity"), dict) else row
        name = str(entity.get("name") or "").strip() if isinstance(entity, dict) else ""
        try:
            exists = bool(name) and (await db.execute(select(Skill.id).where(Skill.name == name))).first() is not None
            if exists and not overwrite_skills:
                outcome["skills_kept"].append(name)
                success += 1
                continue
            await _upsert_skill_from_package(
                db, current_user=current_user, entity=entity, overwrite_existing=overwrite_skills, name_override=None
            )
            outcome["skills_overwritten" if exists else "skills_created"].append(name)
            success += 1
        except Exception as exc:
            failed += 1
            errors.append(f"row {index}: {error_text('data_import_row_failed', exc)}")
    return success, failed, errors, outcome


DELETED_USER = "Deleted user"
DELETED_WORKSPACE = "Deleted Workspace"


def _when(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def backup_history(db: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    exports, imports = await _backup_jobs(db, limit=limit)
    user_ids = {row.created_by for row in [*exports, *imports] if row.created_by}
    project_ids = {row.scope_id for row in exports if row.scope_id} | {
        row.target_project_id for row in imports if row.target_project_id
    }
    names = (
        dict((await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))).all()) if user_ids else {}
    )
    workspaces = (
        dict((await db.execute(select(Project.id, Project.name).where(Project.id.in_(project_ids)))).all())
        if project_ids
        else {}
    )
    entries = [_backup_entry(row, names, workspaces) for row in exports] + [
        _restore_entry(row, names, workspaces) for row in imports
    ]
    return sorted(entries, key=lambda entry: entry["at"] or "", reverse=True)[:limit]


async def _backup_jobs(db: AsyncSession, *, limit: int) -> tuple[list[DataExportJob], list[DataImportJob]]:
    exports = (
        (
            await db.execute(
                select(DataExportJob)
                .where(DataExportJob.export_type == BACKUP_TYPE)
                .order_by(DataExportJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    imports = (
        (
            await db.execute(
                select(DataImportJob)
                .where(DataImportJob.import_type == BACKUP_TYPE)
                .order_by(DataImportJob.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return exports, imports


def _backup_entry(row: DataExportJob, names: dict[str, str], workspaces: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "backup",
        "id": row.id,
        "at": _when(row.created_at),
        "by": names.get(row.created_by, DELETED_USER),
        "by_id": row.created_by,
        "workspace_id": row.scope_id,
        "workspace": workspaces.get(row.scope_id, DELETED_WORKSPACE),
        "status": row.status,
        "downloadable": row.status == "completed" and bool(row.file_url),
        "summary": row.summary_json or {},
        "error": row.error,
    }


def _restore_entry(row: DataImportJob, names: dict[str, str], workspaces: dict[str, str]) -> dict[str, Any]:
    return {
        "kind": "restore",
        "id": row.id,
        "at": _when(row.created_at),
        "by": names.get(row.created_by, DELETED_USER),
        "by_id": row.created_by,
        "workspace_id": row.target_project_id,
        "workspace": workspaces.get(row.target_project_id, DELETED_WORKSPACE),
        "status": row.status,
        "downloadable": False,
        "summary": row.summary_json or {},
        "error": "; ".join(row.errors or []) or None,
    }


__all__ = ["BACKUP_TYPE", "DELETED_USER", "DELETED_WORKSPACE", "backup_history", "restore_skill_rows"]
