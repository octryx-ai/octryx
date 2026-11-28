"""Project discovery for the Knowledge MCP (``knowledge_projects``)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Project, User
from .project import get_user_project_ids


async def mcp_list_projects(db: AsyncSession, *, user: User, bound_project_ids: list[str] | None) -> dict[str, Any]:
    project_ids = await get_user_project_ids(user.id, db)
    bound = {str(item) for item in bound_project_ids or []}
    if bound:
        project_ids = [pid for pid in project_ids if pid in bound]
    if not project_ids:
        return {"projects": []}
    rows = (
        (await db.execute(select(Project).where(Project.id.in_(project_ids), Project.is_active.is_(True))))
        .scalars()
        .all()
    )
    return {"projects": [{"id": row.id, "name": row.name} for row in rows]}


async def load_mcp_knowledge_tool(
    db: AsyncSession,
    *,
    user: User,
    bound_project_ids: list[str] | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "knowledge_projects":
        # No project_id required: this tool exists so a client can discover which project to target.
        return await mcp_list_projects(db, user=user, bound_project_ids=bound_project_ids)
    raise HTTPException(status_code=404, detail="Unknown Knowledge MCP tool")


__all__ = ["load_mcp_knowledge_tool", "mcp_list_projects"]
