"""Agent-group listing and mutation helpers."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...models import AgentGroup
from ..agent_definition_authoring import governed_agent_definition_write
from ..agent_definition_writers import AgentDefinitionWriter
from .helpers import slugify_group_name
from .serialization import serialize_agent_group


async def list_agent_groups(db: AsyncSession, *, user_id: str) -> list[AgentGroup]:
    result = await db.execute(
        select(AgentGroup)
        .options(selectinload(AgentGroup.agents))
        .where(AgentGroup.owner_id == user_id)
        .order_by(AgentGroup.position.asc(), AgentGroup.name.asc())
    )
    return result.scalars().unique().all()


async def create_agent_group(db: AsyncSession, *, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    slug = slugify_group_name(str(payload.get("slug") or name))
    group = AgentGroup(
        id=str(uuid.uuid4()),
        owner_id=user_id,
        project_id=str(payload.get("project_id") or "").strip() or None,
        name=name,
        slug=slug,
        description=str(payload.get("description") or "").strip(),
        category=str(payload.get("category") or "general").strip() or "general",
        position=int(payload.get("position") or 100),
        is_active=bool(payload.get("is_active", True)),
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return serialize_agent_group(group)


async def update_agent_group(
    db: AsyncSession,
    *,
    user_id: str,
    group_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    group = (
        await db.execute(select(AgentGroup).where(AgentGroup.id == group_id, AgentGroup.owner_id == user_id))
    ).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Agent group not found")
    if "name" in payload and payload.get("name") is not None:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Group name is required")
        group.name = name
    if "slug" in payload and payload.get("slug") is not None:
        group.slug = slugify_group_name(str(payload.get("slug") or group.name))
    if "description" in payload and payload.get("description") is not None:
        group.description = str(payload.get("description") or "").strip()
    if "category" in payload and payload.get("category") is not None:
        group.category = str(payload.get("category") or "general").strip() or "general"
    if "project_id" in payload:
        group.project_id = str(payload.get("project_id") or "").strip() or None
    if "position" in payload and payload.get("position") is not None:
        group.position = int(payload.get("position") or 100)
    if "is_active" in payload and payload.get("is_active") is not None:
        group.is_active = bool(payload.get("is_active"))
    await db.commit()
    await db.refresh(group)
    return serialize_agent_group(group)


async def delete_agent_group(db: AsyncSession, *, user_id: str, group_id: str) -> dict[str, Any]:
    group = (
        await db.execute(
            select(AgentGroup)
            .options(selectinload(AgentGroup.agents))
            .where(AgentGroup.id == group_id, AgentGroup.owner_id == user_id)
        )
    ).scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=404, detail="Agent group not found")
    # Detaching the members rewrites checksum-bearing content: ``group_id`` is part of
    # the Agent Definition revision snapshot, so this is an aggregate write and passes
    # the one governed boundary like every other one. The lookup and the 404
    # stay *outside* the scope, so a rejected request leaves no revision and no audit
    # row.
    #
    # The detach is written out rather than left to SQLAlchemy's foreign-key nulling
    # on parent delete: the boundary collects touched rows in ``before_flush``, and
    # relationship-driven nulling happens later, inside flush processing.
    async with governed_agent_definition_write(
        db,
        writer=AgentDefinitionWriter.PANEL_AGENT_GROUP_DELETE,
        actor_id=user_id,
    ):
        for agent in group.agents or []:
            agent.group_id = None
        await db.delete(group)
        await db.commit()
    return {"status": "deleted"}
