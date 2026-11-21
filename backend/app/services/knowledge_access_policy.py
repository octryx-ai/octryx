"""Which projects a project's entity-graph knowledge reads may span (``knowledge_retrieve``).

The scope is the project itself, the configured central knowledge projects
(``central_knowledge_project_ids``), the default workspace knowledge bases (projects whose
``knowledge_base.scope`` is ``workspace``/``central``, unless the project's ``knowledge_access`` opts
out), and the active knowledge mounts (``knowledge_mounts``).

Governed cross-Workspace reads of the Knowledge module are Workspace bindings, not this policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project
from .project_resource_policy import normalize_knowledge_mounts, normalize_mapping


@dataclass(frozen=True)
class KnowledgeAccessPolicy:
    project_id: str
    direct_project_ids: list[str] = field(default_factory=list)

    @property
    def candidate_project_ids(self) -> list[str]:
        return list(dict.fromkeys(self.direct_project_ids))


async def load_knowledge_access_policy(db: AsyncSession, *, project_id: str | None) -> KnowledgeAccessPolicy:
    base_project_id = str(project_id or "").strip()
    if not base_project_id:
        return KnowledgeAccessPolicy(project_id="", direct_project_ids=[])
    project = await db.get(Project, base_project_id)
    if project is None:
        return KnowledgeAccessPolicy(project_id=base_project_id, direct_project_ids=[])
    direct_project_ids = await _resolve_direct_knowledge_project_ids(db, project=project)
    return KnowledgeAccessPolicy(project_id=project.id, direct_project_ids=direct_project_ids)


async def _resolve_direct_knowledge_project_ids(db: AsyncSession, *, project: Project) -> list[str]:
    """The reading Workspace and the Workspaces whose knowledge it may read. A private Workspace is never a source
    for any other Workspace: its own knowledge is read only from inside it."""
    project_ids = await _direct_knowledge_project_ids(db, project=project)
    others = [project_id for project_id in project_ids if project_id != project.id]
    if not others:
        return project_ids
    private = {row[0] for row in (await db.execute(
        select(Project.id).where(Project.id.in_(others), Project.access_mode == "private"))).all()}
    return [project_id for project_id in project_ids if project_id not in private]


async def _direct_knowledge_project_ids(db: AsyncSession, *, project: Project) -> list[str]:
    project_ids = [project.id]
    config = normalize_mapping(project.config)
    for central_project_id in _normalize_config_project_ids(config.get("central_knowledge_project_ids")):
        if central_project_id not in project_ids:
            project_ids.append(central_project_id)
    if _allows_default_workspace_knowledge(config):
        for central_project_id in await _resolve_configured_workspace_knowledge_project_ids(db):
            if central_project_id not in project_ids:
                project_ids.append(central_project_id)
    mount_ids = [
        mount["source_project_id"]
        for mount in normalize_knowledge_mounts(config.get("knowledge_mounts"))
        if mount["source_project_id"] != project.id
    ]
    if not mount_ids:
        return project_ids
    active_source_ids = {
        row.id
        for row in (
            await db.execute(select(Project).where(Project.id.in_(mount_ids), Project.is_active.is_(True)))
        ).scalars()
    }
    for source_project_id in mount_ids:
        if source_project_id in active_source_ids and source_project_id not in project_ids:
            project_ids.append(source_project_id)
    return project_ids


async def _resolve_configured_workspace_knowledge_project_ids(db: AsyncSession) -> list[str]:
    rows = (
        (await db.execute(select(Project).where(Project.is_active.is_(True)).order_by(Project.created_at.asc())))
        .scalars()
        .all()
    )
    project_ids: list[str] = []
    for project in rows:
        config = normalize_mapping(project.config)
        knowledge_base = normalize_mapping(config.get("knowledge_base"))
        if str(knowledge_base.get("scope") or "").strip().lower() not in {"workspace", "central"}:
            continue
        if knowledge_base.get("default_project_access") is False:
            continue
        project_ids.append(project.id)
    return project_ids


def _allows_default_workspace_knowledge(config: dict[str, Any]) -> bool:
    access_config = normalize_mapping(config.get("knowledge_access"))
    mode = str(access_config.get("mode") or "").strip().lower()
    if mode in {"limited", "private", "disabled"}:
        return False
    if access_config.get("default_workspace_access") is False:
        return False
    return True


def _normalize_config_project_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    return list(dict.fromkeys(text for text in (str(item or "").strip() for item in raw_items) if text))


__all__ = ["KnowledgeAccessPolicy", "load_knowledge_access_policy"]
