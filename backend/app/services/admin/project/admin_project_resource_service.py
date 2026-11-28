"""Project resource assignment helpers for repositories and knowledge-base mounts."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import AuditLog, CodeRepository, Project
from ...project_resource_policy import (
    REPOSITORY_OPERATION_KEYS,
    normalize_knowledge_mounts,
    normalize_mapping,
    normalize_repository_operations,
)

KNOWLEDGE_ACCESS_MODES = {"default", "limited", "private"}


def _serialize_repository_resource(repo: CodeRepository) -> dict[str, Any]:
    config = normalize_mapping(repo.config_json)
    operations = normalize_repository_operations(config.get("operation_policy"))
    return {
        "id": repo.id,
        "name": repo.name,
        "provider": repo.provider,
        "repo_root": repo.repo_root,
        "remote_url": repo.remote_url,
        "default_branch": repo.default_branch,
        "is_active": bool(repo.is_active),
        "last_index_status": repo.last_index_status,
        "operation_policy": operations,
    }


def _knowledge_base_option(project: Project) -> dict[str, Any]:
    return {"project_id": project.id, "project_name": project.name}


async def get_project_resource_assignments(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    repositories = (
        (
            await db.execute(
                select(CodeRepository)
                .where(CodeRepository.project_id == project_id)
                .order_by(CodeRepository.name.asc())
            )
        )
        .scalars()
        .all()
    )
    projects = (
        (
            await db.execute(
                select(Project).where(Project.is_active.is_(True), Project.access_mode != "private").order_by(Project.name.asc())
            )
        )
        .scalars()
        .all()
    )
    config = normalize_mapping(project.config)
    mounts = normalize_knowledge_mounts(config.get("knowledge_mounts"))
    mounted_source_ids = {mount["source_project_id"] for mount in mounts}
    project_by_id = {item.id: item for item in projects}
    serialized_mounts = []
    for mount in mounts:
        source_project = project_by_id.get(mount["source_project_id"])
        serialized_mounts.append(
            {
                **mount,
                "source_project_name": source_project.name if source_project else "Unknown project",
            }
        )
    available_sources = [_knowledge_base_option(item) for item in projects if item.id != project.id]

    return {
        "project": {"id": project.id, "name": project.name},
        "repositories": [_serialize_repository_resource(repo) for repo in repositories],
        "knowledge_base": {"project_id": project.id, "project_name": project.name, "access": "owner"},
        "knowledge_access": _normalize_knowledge_access_policy(config.get("knowledge_access")),
        "knowledge_mounts": serialized_mounts,
        "available_knowledge_bases": [
            item for item in available_sources if item["project_id"] not in mounted_source_ids
        ],
        "policy_keys": list(REPOSITORY_OPERATION_KEYS),
    }


async def update_project_resource_assignments(
    db: AsyncSession,
    *,
    project_id: str,
    payload: dict[str, Any],
    actor_user_id: str | None = None,
) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if "repository_policies" in payload:
        await _update_repository_policies(db, project_id=project_id, items=payload.get("repository_policies") or [])

    if "knowledge_mounts" in payload:
        await _update_knowledge_mounts(
            db,
            project=project,
            items=payload.get("knowledge_mounts") or [],
            actor_user_id=actor_user_id,
        )

    if "knowledge_access" in payload:
        _update_knowledge_access_policy(project=project, value=payload.get("knowledge_access"))

    await db.commit()
    return await get_project_resource_assignments(db, project_id=project_id)


async def _update_repository_policies(db: AsyncSession, *, project_id: str, items: list[dict[str, Any]]) -> None:
    repository_ids = [str(item.get("repository_id") or "").strip() for item in items]
    repositories_by_id: dict[str, CodeRepository] = {}
    if repository_ids:
        rows = (
            (
                await db.execute(
                    select(CodeRepository).where(
                        CodeRepository.id.in_(repository_ids),
                        CodeRepository.project_id == project_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        repositories_by_id = {repo.id: repo for repo in rows}

    for item in items:
        repository_id = str(item.get("repository_id") or "").strip()
        repo = repositories_by_id.get(repository_id)
        if repo is None:
            raise HTTPException(status_code=400, detail="Repository policy references an unknown project repository")
        config = normalize_mapping(repo.config_json)
        config["operation_policy"] = normalize_repository_operations(item.get("operations"))
        repo.config_json = config


async def _update_knowledge_mounts(
    db: AsyncSession,
    *,
    project: Project,
    items: list[dict[str, Any]],
    actor_user_id: str | None,
) -> None:
    requested_mounts = normalize_knowledge_mounts(items)
    source_project_ids = [item["source_project_id"] for item in requested_mounts]
    await _require_active_source_projects(
        db,
        target_project_id=project.id,
        source_project_ids=source_project_ids,
        resource_label="Knowledge mount",
    )
    config = normalize_mapping(project.config)
    previous_mounts = normalize_knowledge_mounts(config.get("knowledge_mounts"))
    config["knowledge_mounts"] = requested_mounts
    project.config = config
    if previous_mounts != requested_mounts:
        _record_resource_audit(
            db,
            actor_user_id=actor_user_id,
            action="knowledge_mounts.updated",
            project_id=project.id,
            resource_type="project_knowledge_mounts",
            resource_id=project.id,
            details={"before": previous_mounts, "after": requested_mounts},
        )


def _update_knowledge_access_policy(*, project: Project, value: Any) -> None:
    config = normalize_mapping(project.config)
    config["knowledge_access"] = _normalize_knowledge_access_policy(value)
    project.config = config


def _normalize_knowledge_access_policy(value: Any) -> dict[str, Any]:
    raw = normalize_mapping(value)
    mode = str(raw.get("mode") or "").strip().lower()
    if mode not in KNOWLEDGE_ACCESS_MODES:
        mode = "default"
    default_workspace_access = raw.get("default_workspace_access")
    if default_workspace_access is None:
        default_workspace_access = mode == "default"
    return {
        "mode": mode,
        "default_workspace_access": bool(default_workspace_access) and mode == "default",
    }


async def _require_active_source_projects(
    db: AsyncSession,
    *,
    target_project_id: str,
    source_project_ids: list[str],
    resource_label: str,
) -> None:
    if target_project_id in source_project_ids:
        raise HTTPException(status_code=400, detail=f"{resource_label}s cannot reference the same project")
    if not source_project_ids:
        return
    found_ids = {
        row.id
        for row in (
            await db.execute(select(Project).where(Project.id.in_(source_project_ids), Project.is_active.is_(True),
                                                   Project.access_mode != "private"))
        ).scalars()
    }
    if set(source_project_ids) - found_ids:
        raise HTTPException(status_code=400, detail=f"{resource_label} references an unknown active project")


def _record_resource_audit(
    db: AsyncSession,
    *,
    actor_user_id: str | None,
    action: str,
    project_id: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any],
) -> None:
    if not actor_user_id:
        return
    db.add(
        AuditLog(
            user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            project_id=project_id,
            details={"project_id": project_id, **details},
        )
    )


__all__ = [
    "get_project_resource_assignments",
    "update_project_resource_assignments",
]
