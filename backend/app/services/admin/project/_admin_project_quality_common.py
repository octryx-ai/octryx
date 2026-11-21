"""Shared helpers for project quality admin service functions."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import Project
from .admin_project_quality_overview import list_projects_for_quality_config
from .admin_project_quality_project import serialize_project as _serialize_project


def _normalize_config_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


async def _get_project(db: AsyncSession, project_id: str) -> Project:
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _project_config(project: Project) -> dict[str, Any]:
    return dict(project.config or {}) if isinstance(project.config, dict) else {}


async def _serialize_project_after_refresh(db: AsyncSession, project: Project) -> dict[str, Any]:
    await db.refresh(project)
    return _serialize_project(project)


async def _project_after_update_payload(db: AsyncSession, project_id: str) -> dict[str, Any]:
    projects = await list_projects_for_quality_config(db)
    selected = next((item for item in projects if item["id"] == project_id), None)
    if not selected:
        raise HTTPException(status_code=404, detail="Project not found after update")
    return selected
