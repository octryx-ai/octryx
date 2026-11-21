"""Admin-owned project config read and merge helpers.

The key-owner registry and the per-key normalization live in the
``_admin_project_config_*`` modules next to this one.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from ...prompt_governance import record_project_prompt_revisions
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
    change_source: str | None = None,
    replace_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Merge a partial config into ``project.config`` without committing.

    ``replace_keys``: top-level keys whose dict value replaces the stored one instead of being merged into it (a
    section that must be able to drop a sub-key, e.g. a budget going back to inherit).

    Only the top-level keys present in ``patch`` change; a dict value is merged one level
    into the existing dict under the same key. Unrelated keys are always kept, and every
    provided key passes the owner's normalization. This is the single write path for
    project config, so no caller can replace the whole config by accident.
    """

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
        before=previous_config,
        after=current_config,
        # The keys this write carried, also when a value is saved unchanged (an explicit admin decision).
        details={"project_id": project.id, "project_name": project.name, "patched_keys": sorted(normalized_patch)},
    )
    revision_kwargs = {"change_source": change_source} if change_source else {}
    await record_project_prompt_revisions(
        db,
        project_id=project.id,
        before_config=previous_config,
        after_config=current_config,
        created_by=actor_user_id,
        **revision_kwargs,
    )
    return current_config


async def _get_project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


CODE_CONNECTION_KEY_REFUSED = "project_config_connection_key"


def refuse_connection_keys(patch: dict[str, Any]) -> None:
    """422 when a write would put a connector's target, credential or selector into ``Project.config``.

    A connection lives in the Workspace's tool entry: ``Project.config`` is never read for
    it. Field names only.
    """
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
