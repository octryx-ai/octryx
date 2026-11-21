"""Shared scope pieces of the extra MCP tools: the authorized Workspace, the chat's config and refusals.

``run_governed_mcp_tool`` hands every tool a ``ToolContext`` whose only scope input is the connection
Workspace (``project_config = {"project_id": ...}``, ``project_ids = [workspace]``). Two things are
added here, never from tool arguments:

- :class:`WorkspaceBoundTool` authorizes that Workspace for the user like a Knowledge tool run
  (``authorize_tool_workspace``), so a Workspace the user cannot read is ``not_found`` before a chat
  tool that does not authorize on its own (diagrams, web search) runs;
- :func:`chat_tool_project_config` builds the project config exactly as a chat turn does
  (``agent/core/context/run_context_config.assemble_turn_project_config``): the Workspace row merged
  with its tool configurations and connector policies, plus ``project_id``, ``project_role`` and
  ``user_roles``. Connector tools read their connection (URL, credentials, allowlists) from it; no
  session workspace root or engineering runtime is added, because an MCP call has neither.
"""

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
    """One closed refusal: a fixed state, a fixed reason code and a fixed message."""
    return {"state": state, "reason": reason, "error": error}


async def _user_roles(db: AsyncSession, user_id: str) -> list[str]:
    statement = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    return [str(name) for name in (await db.execute(statement)).scalars()] or list(_DEFAULT_ROLES)


async def chat_tool_project_config(db: AsyncSession, *, user_id: str, workspace_id: str) -> dict[str, Any]:
    """The project config a chat turn of this user in this Workspace hands its tools."""
    return {
        **(await get_project_config(workspace_id, db)),
        "project_id": workspace_id,
        "project_role": await get_project_role_for_user(db, user_id, workspace_id) or "",
        "user_roles": await _user_roles(db, user_id),
    }


class WorkspaceBoundTool:
    """A chat tool that runs only after the connection Workspace is authorized for the user."""

    def __init__(self, tool: Any) -> None:
        self._tool = tool
        self.name = tool.name

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        authorized = await authorized_workspace(params, context)
        if type(authorized) is dict:
            return authorized
        return await self._tool.execute(params, context)


__all__ = ["WorkspaceBoundTool", "chat_tool_project_config", "refusal"]
