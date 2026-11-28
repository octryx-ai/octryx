"""Shared scope pieces of the extra MCP tools: the authorized Workspace, the chat's config and refusals. Nothing is
taken from tool arguments."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Role, UserRole
from ..tools.context import ToolContext
from ..tools.knowledge_evidence._scope import authorized_workspace
from .access_control import get_project_role_for_user
from .project import get_project_config

_DEFAULT_ROLES = ["viewer"]


def refusal(state: str, reason: str, error: str) -> dict[str, Any]:
    return {"state": state, "reason": reason, "error": error}


async def user_platform_roles(db: AsyncSession, user_id: str) -> list[str]:
    statement = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    return [str(name) for name in (await db.execute(statement)).scalars()] or list(_DEFAULT_ROLES)


async def chat_tool_project_config(db: AsyncSession, *, user_id: str, workspace_id: str) -> dict[str, Any]:
    return {
        **(await get_project_config(workspace_id, db)),
        "project_id": workspace_id,
        "project_role": await get_project_role_for_user(db, user_id, workspace_id) or "",
        "user_roles": await user_platform_roles(db, user_id),
    }


class WorkspaceBoundTool:
    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = tool.name

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        return await self._tool.execute(params, context)


__all__ = ["WorkspaceBoundTool", "chat_tool_project_config", "refusal", "user_platform_roles"]
