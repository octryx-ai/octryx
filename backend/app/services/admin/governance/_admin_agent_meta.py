"""Read-only queries behind the admin-panel agent builder: the agent list and the form metadata."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ....models import AgentDefinition, AgentGroup, Project
from ...agent_mode import list_agent_modes, serialize_agent_mode
from ...agent_visibility import agent_access
from ...project.private_workspace import foreign_private_filter


async def list_agent_definitions(db: AsyncSession, *, user_id: str) -> list[AgentDefinition]:
    access = await agent_access(db, user_id)
    result = await db.execute(
        select(AgentDefinition)
        .options(selectinload(AgentDefinition.steps), selectinload(AgentDefinition.group))
        .where(access.visible_clause())
        .order_by(AgentDefinition.updated_at.desc(), AgentDefinition.name.asc())
    )
    return result.scalars().unique().all()


async def build_agent_builder_meta(
    db: AsyncSession,
    *,
    user_id: str,
    runtime_options: list[dict[str, Any]],
    thinking_levels: list[str],
    tool_options: list[str],
) -> dict[str, Any]:
    projects = (await db.execute(
        select(Project).where(foreign_private_filter(user_id)).order_by(Project.name.asc()))).scalars().all()
    agent_groups = (
        (
            await db.execute(
                select(AgentGroup)
                .where(AgentGroup.owner_id == user_id)
                .order_by(AgentGroup.position.asc(), AgentGroup.name.asc())
            )
        )
        .scalars()
        .all()
    )
    agent_modes = [serialize_agent_mode(mode) for mode in list_agent_modes()]
    return {
        "projects": [
            {"id": project.id, "name": project.name, "is_active": bool(project.is_active)}
            for project in projects
        ],
        "agent_groups": [
            {
                "id": group.id,
                "name": group.name,
                "slug": group.slug,
                "description": group.description or "",
                "category": group.category or "general",
                "projectId": group.project_id or "",
                "position": int(group.position or 100),
                "isActive": bool(group.is_active),
            }
            for group in agent_groups
        ],
        "runtime_options": runtime_options,
        "thinking_levels": thinking_levels,
        "agent_modes": agent_modes,
        "step_type_options": [
            "analysis",
            "tooling",
            "documentation",
            "change",
            "knowledge",
            "tdd_cycle",
            "self_review",
            "handover",
        ],
        "tool_options": tool_options,
        "owner_id": user_id,
    }
