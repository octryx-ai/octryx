"""Configuration-focused project quality admin operations."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...repository_bootstrap import normalize_repository_bootstrap_config
from ...runtime_policy_bundle import normalize_runtime_policy_config
from ._admin_project_quality_common import (
    _get_project,
    _normalize_config_value,
    _project_config,
    _serialize_project_after_refresh,
)


async def update_project_repo_quality_config(
    db: AsyncSession,
    *,
    project_id: str,
    repo_code_quality: dict[str, Any],
) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    config = _project_config(project)
    normalized = _normalize_config_value(repo_code_quality)

    if normalized:
        config["repo_code_quality"] = normalized
    else:
        config.pop("repo_code_quality", None)

    project.config = config
    await db.commit()
    return await _serialize_project_after_refresh(db, project)


async def update_project_runtime_policy(
    db: AsyncSession,
    *,
    project_id: str,
    runtime_policy: dict[str, Any],
) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    config = _project_config(project)
    normalized = normalize_runtime_policy_config(runtime_policy if isinstance(runtime_policy, dict) else {})

    if (
        normalized["default_bundle"]
        or normalized["environment_bundles"]
        or normalized["active_environment"]
    ):
        config["runtime_policy"] = normalized
    else:
        config.pop("runtime_policy", None)

    project.config = config
    await db.commit()
    return await _serialize_project_after_refresh(db, project)


async def update_project_repository_bootstrap(
    db: AsyncSession,
    *,
    project_id: str,
    repository_bootstrap: dict[str, Any],
) -> dict[str, Any]:
    project = await _get_project(db, project_id)
    config = _project_config(project)
    raw = _normalize_config_value(repository_bootstrap)

    if raw:
        config["repository_bootstrap"] = normalize_repository_bootstrap_config(raw)
    else:
        config.pop("repository_bootstrap", None)

    project.config = config
    await db.commit()
    return await _serialize_project_after_refresh(db, project)
