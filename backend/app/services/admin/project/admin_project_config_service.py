"""Admin-owned project config read and merge helpers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from ...tool_config.connection_fields import refused_connection_keys
from ..governance.admin_config_audit_service import record_admin_config_audit
from ._admin_project_config_normalize import _normalize_project_config_value


async def get_project_config_payload(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    return _project_config_payload(project)


async def merge_project_config(
    db: AsyncSession,
    *,
    project_id: str,
    patch: dict[str, Any],
    actor_user_id: str,
) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    await apply_project_config_patch(db, project=project, patch=patch, actor_user_id=actor_user_id)
    await db.commit()
    return _project_config_payload(project)


async def apply_project_config_patch(
    db: AsyncSession,
    *,
    project: Project,
    patch: dict[str, Any],
    actor_user_id: str,
    replace_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    previous_config = _project_config(project)
    current_config = dict(previous_config)
    normalized_patch = _normalize_patch_mapping(patch)
    refuse_connection_keys(normalized_patch)

    for key, value in normalized_patch.items():
        if isinstance(value, dict) and isinstance(current_config.get(key), dict) and key not in replace_keys:
            merged_value = {**current_config[key], **value}
        else:
            merged_value = value
        current_config[key] = _normalize_project_config_value(key, merged_value)

    project.config = current_config
    record_admin_config_audit(
        db,
        actor_user_id=actor_user_id,
        action="admin.project_config.updated",
        resource_type="project_config",
        resource_id=project.id,
        project_id=project.id,
        before=previous_config,
        after=current_config,
        # The keys this write carried, also when a value is saved unchanged (an explicit admin decision).
        details={"project_id": project.id, "project_name": project.name, "patched_keys": sorted(normalized_patch)},
    )
    return current_config


async def _get_project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


CODE_CONNECTION_KEY_REFUSED = "project_config_connection_key"


def refuse_connection_keys(patch: dict[str, Any]) -> None:
    refused = refused_connection_keys(patch)
    if refused:
        raise HTTPException(
            status_code=422,
            detail={"errors": [{
                "code": CODE_CONNECTION_KEY_REFUSED,
                "message": "Connection fields belong to the Workspace's connector connection, not the project "
                f"config: {', '.join(refused)}.",
            }]},
        )


def _project_config(project: Project) -> dict[str, Any]:
    return dict(project.config or {}) if isinstance(project.config, dict) else {}


def _project_config_payload(project: Project) -> dict[str, Any]:
    return {"id": project.id, "name": project.name, "config": _project_config(project)}


def _normalize_patch_mapping(patch: dict[str, Any] | None) -> dict[str, Any]:
    return dict(patch or {}) if isinstance(patch, dict) else {}
