"""Admin project lifecycle operations."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User, UserProject
from app.services.admin.project.admin_project_config_service import refuse_connection_keys
from app.services.knowledge.projection.workspace_classification_default import (
    new_workspace_default,
    stamp_new_workspace_default,
)
from app.services.project_deletion_cascade import deactivate_project_bindings
from app.services.project_template_service import PROJECT_SOURCE_MANUAL
from app.services.trace_capture import ensure_default_trace_capture_config

logger = logging.getLogger(__name__)

def _clean_project_name(name: str) -> str:
    cleaned = str(name or "").strip()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name is required")
    if len(cleaned) > 200:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Project name is too long")
    return cleaned


def _project_response(project: Project) -> dict[str, Any]:
    config = project.config or {}
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "config": config,
        "is_active": bool(project.is_active),
        "source_type": project.source_type or PROJECT_SOURCE_MANUAL,
        "template_key": project.template_key,
        "template_version": project.template_version,
        "template_metadata": project.template_metadata or {},
        "is_system": bool(project.is_system),
    }


async def create_project_for_admin(
    db: AsyncSession,
    *,
    current_user: User,
    name: str,
    description: str | None,
    config: dict[str, Any] | None,
    is_active: bool = True,
) -> Project:
    project_name = _clean_project_name(name)
    existing = (await db.execute(select(Project).where(Project.name == project_name))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project name already exists")

    # A connection lives in the Workspace's tool entry, never in Project.config (coded 422).
    refuse_connection_keys(dict(config or {}))
    default = await new_workspace_default(db)
    project = Project(
        id=str(uuid.uuid4()),
        name=project_name,
        description=description,
        config=ensure_default_trace_capture_config(config),
        is_active=is_active,
        source_type=PROJECT_SOURCE_MANUAL,
        is_system=False,
    )
    # A new Workspace gets the Instance default level at creation (a Workspace without a level
    # is refused seats and remote models). A level in the submitted config wins; nothing is written without a default.
    stamp_new_workspace_default(db, project, default, current_user.id)
    db.add(project)
    await db.flush()
    db.add(UserProject(user_id=current_user.id, project_id=project.id, role="owner"))
    await allow_all_cleared_models(db, project.id, actor_id=current_user.id)
    return project


async def allow_all_cleared_models(db: AsyncSession, project_id: str, *, actor_id: str) -> None:
    # Every model cleared for the level, so device runs always find one; never blocks the creation.
    from .workspace_models.contract import MODE_ALL
    from .workspace_models.store import read_models, save_models

    try:
        contract = dict((await read_models(db, project_id)).get("contract") or {})
        body = {**contract, "mode": MODE_ALL, "selected": [], "default": None}
        await save_models(db, project_id, body, actor_id=actor_id, platform_admin=True)
    except Exception:  # noqa: BLE001 - the Workspace exists either way; its Models page shows what is allowed
        logger.warning("workspace.create allow_all_models_failed project=%s", project_id, exc_info=True)


async def update_project_for_admin(
    db: AsyncSession,
    *,
    project_id: str,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> Project:
    project = await _get_project_or_404(db, project_id)
    if name is not None:
        project_name = _clean_project_name(name)
        duplicate = (await db.execute(select(Project).where(Project.name == project_name))).scalar_one_or_none()
        if duplicate is not None and duplicate.id != project.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project name already exists")
        project.name = project_name
    if description is not None:
        project.description = description
    if is_active is not None:
        if project.is_system and not is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System project cannot be deactivated")
        project.is_active = is_active
    return project


async def archive_project_for_admin(db: AsyncSession, *, project_id: str) -> Project:
    project = await _get_project_or_404(db, project_id)
    if project.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System project cannot be archived")
    project.is_active = False
    project.template_metadata = {
        **(project.template_metadata if isinstance(project.template_metadata, dict) else {}),
        "archived": True,
    }
    return project


async def restore_project_for_admin(db: AsyncSession, *, project_id: str) -> Project:
    project = await _get_project_or_404(db, project_id)
    project.is_active = True
    project.template_metadata = {
        **(project.template_metadata if isinstance(project.template_metadata, dict) else {}),
        "archived": False,
        "deleted": False,
    }
    return project


async def delete_project_for_admin(db: AsyncSession, *, project_id: str, actor: User) -> Project:
    project = await _get_project_or_404(db, project_id)
    if project.is_system:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System project cannot be deleted")
    project.is_active = False
    project.template_metadata = {
        **(project.template_metadata if isinstance(project.template_metadata, dict) else {}),
        "archived": True,
        "deleted": True,
        "delete_mode": "soft",
    }
    await deactivate_project_bindings(db, project_id=project.id, actor=actor)
    return project


async def _get_project_or_404(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def project_to_response(project: Project) -> dict[str, Any]:
    return _project_response(project)
