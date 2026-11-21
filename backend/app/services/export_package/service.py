"""Canonical service surface for export package operations."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentDefinition, ExportPackage, ImportLog, Skill, Task, User
from .content import serialize_agent_content, serialize_skill_content, serialize_task_content
from .core import (
    SUPPORTED_PACKAGE_TYPES,
    checksum_for_content,
    serialize_export_package_row,
    serialize_import_log_row,
)

SerializeTaskContentFn = Callable[[AsyncSession, Task], Awaitable[dict[str, Any]]]


async def list_export_packages(
    db: AsyncSession,
    *,
    package_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(ExportPackage).order_by(ExportPackage.exported_at.desc()).limit(max(1, min(limit, 100)))
    if package_type:
        stmt = stmt.where(ExportPackage.package_type == package_type)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_export_package_row(row) for row in rows]


async def list_import_logs(
    db: AsyncSession,
    *,
    package_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(ImportLog).order_by(ImportLog.imported_at.desc()).limit(max(1, min(limit, 100)))
    if package_type:
        stmt = stmt.where(ImportLog.package_type == package_type)
    rows = (await db.execute(stmt)).scalars().all()
    return [serialize_import_log_row(row) for row in rows]


async def get_export_package(db: AsyncSession, *, package_id: str) -> dict[str, Any]:
    row = await db.get(ExportPackage, package_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Export package not found")
    return serialize_export_package_row(row)


async def _serialize_skill_content(db: AsyncSession, skill: Skill) -> dict[str, Any] | None:
    return await serialize_skill_content(db, skill)


def _serialize_agent_content(agent: AgentDefinition) -> dict[str, Any]:
    return serialize_agent_content(agent)


async def _serialize_task_content(db: AsyncSession, task: Task) -> dict[str, Any]:
    return await serialize_task_content(db, task)


async def create_export_package(
    db: AsyncSession,
    *,
    current_user: User,
    package_type: str,
    entity_id: str,
    serialize_task_content_func: SerializeTaskContentFn = _serialize_task_content,
) -> dict[str, Any]:
    normalized_type = str(package_type or "").strip().lower()
    if normalized_type not in SUPPORTED_PACKAGE_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported package type")
    if normalized_type == "skill":
        skill = await db.get(Skill, entity_id)
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        content_json = await _serialize_skill_content(db, skill)
        if content_json is None:
            raise HTTPException(status_code=409, detail="Skill has no published version to export")
        entity_name = skill.name
        source_project_id = None
    elif normalized_type == "agent":
        result = await db.execute(
            select(AgentDefinition).options(selectinload(AgentDefinition.steps)).where(AgentDefinition.id == entity_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=404, detail="Agent not found")
        content_json = _serialize_agent_content(agent)
        entity_name = agent.name
        source_project_id = agent.project_id
    else:
        result = await db.execute(select(Task).options(selectinload(Task.steps)).where(Task.id == entity_id))
        task = result.scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        content_json = await serialize_task_content_func(db, task)
        entity_name = task.name
        source_project_id = task.project_id

    checksum = checksum_for_content(content_json)
    row = ExportPackage(
        id=str(uuid.uuid4()),
        package_type=normalized_type,
        entity_name=entity_name,
        source_entity_type=normalized_type,
        source_entity_id=entity_id,
        source_project_id=source_project_id,
        content_json=content_json,
        checksum=checksum,
        exported_by=current_user.id,
    )
    db.add(row)
    await db.commit()
    return await get_export_package(db, package_id=row.id)


__all__ = [
    "_serialize_agent_content",
    "_serialize_skill_content",
    "_serialize_task_content",
    "create_export_package",
    "get_export_package",
    "list_export_packages",
    "list_import_logs",
]
