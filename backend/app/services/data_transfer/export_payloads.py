"""Export payloads: Workspace backup, admin config backup and task/agent definition exports."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.services.export_package import (
    _serialize_agent_content,
    _serialize_skill_content,
    _serialize_task_content,
)

from ...models import AgentDefinition, Project, Skill, Task
from ...models.agent.skill_catalog import SKILL_KIND_SKILL
from ..project.private_workspace import PRIVATE_ACCESS_MODE

ADMIN_CONFIG_INCLUDED_SECTIONS = ["project_config", "tasks", "agents", "skills"]
ADMIN_CONFIG_EXCLUDED_SECTIONS = [
    "sessions",
    "messages",
    "message_feedback",
    "task_runs",
    "tool_calls",
    "turn_traces",
    "thread_context",
    "audit_logs",
    "runtime_history",
    "raw_secrets",
]


async def _build_project_backup_payload(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    task_rows = (
        (
            await db.execute(
                select(Task)
                .options(selectinload(Task.steps))
                .where(Task.project_id == project_id)
                .order_by(Task.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    agent_rows = (
        (
            await db.execute(
                select(AgentDefinition)
                .options(selectinload(AgentDefinition.steps))
                .where(AgentDefinition.project_id == project_id)
            )
        )
        .scalars()
        .all()
    )
    published_skills = (
        select(Skill)
        .where(Skill.kind == SKILL_KIND_SKILL, Skill.published_version_id.is_not(None))
        .order_by(Skill.name.asc())
    )
    skill_rows = (await db.execute(published_skills)).scalars().all()
    skills = [content for row in skill_rows if (content := await _serialize_skill_content(db, row)) is not None]

    return {
        "format_version": 1,
        "export_type": "project_backup",
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description or "",
            "config": project.config or {},
            "is_active": bool(project.is_active),
            "source_type": project.source_type,
            "template_key": project.template_key,
            "template_version": project.template_version,
            "template_metadata": project.template_metadata or {},
            "is_system": bool(project.is_system),
        },
        "tasks": [await _serialize_task_content(db, row) for row in task_rows],
        "agents": [_serialize_agent_content(row) for row in agent_rows],
        "skills": skills,
    }


async def _build_admin_config_backup_payload(db: AsyncSession, *, project_id: str) -> dict[str, Any]:
    payload = await _build_project_backup_payload(db, project_id=project_id)
    payload["export_type"] = "admin_config_backup"
    payload["manifest"] = {
        "format_version": 1,
        "package_type": "admin_config_backup",
        "included_sections": list(ADMIN_CONFIG_INCLUDED_SECTIONS),
        "excluded_sections": list(ADMIN_CONFIG_EXCLUDED_SECTIONS),
        "restore_target": "project",
        "secret_policy": "raw secrets are excluded",
    }
    return payload


async def _build_definition_export_payload(
    db: AsyncSession,
    *,
    export_type: str,
    project_id: str | None,
) -> dict[str, Any]:
    # Like a named export, a bulk one never carries a private Workspace's definitions.
    private = select(Project.id).where(Project.access_mode == PRIVATE_ACCESS_MODE)
    if export_type == "task_definitions":
        stmt = (select(Task).options(selectinload(Task.steps)).order_by(Task.created_at.asc())
                .where(Task.project_id.is_(None) | Task.project_id.not_in(private)))
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)
        rows = (await db.execute(stmt)).scalars().all()
        return {
            "format_version": 1,
            "export_type": export_type,
            "project_id": project_id,
            "tasks": [await _serialize_task_content(db, row) for row in rows],
        }

    stmt = (
        select(AgentDefinition).options(selectinload(AgentDefinition.steps)).order_by(AgentDefinition.created_at.asc())
        .where(AgentDefinition.project_id.is_(None) | AgentDefinition.project_id.not_in(private))
    )
    if project_id:
        stmt = stmt.where(AgentDefinition.project_id == project_id)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "format_version": 1,
        "export_type": export_type,
        "project_id": project_id,
        "agents": [_serialize_agent_content(row) for row in rows],
    }
