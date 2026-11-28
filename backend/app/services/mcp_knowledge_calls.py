"""The audited call paths of the Knowledge MCP tool families (scope checked and session opened by the protocol)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import Context
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .content_security.knowledge_fence import fence_knowledge_result
from .mcp_auto_session import mcp_client_name, record_mcp_tool_activity
from .mcp_code_graph_tools import MCP_CODE_GRAPH_TOOL_HANDLERS
from .mcp_entity_graph_tools import MCP_ENTITY_GRAPH_TOOL_HANDLERS
from .mcp_external_session import mcp_approval_request, mcp_session_ingest
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit

GRAPH_TOOL_HANDLERS = {**MCP_ENTITY_GRAPH_TOOL_HANDLERS, **MCP_CODE_GRAPH_TOOL_HANDLERS}
_EXTERNAL_SESSION_TOOL_SCOPES = {
    "session_ingest": "session:write",
    "approval_request": "write",
}
_EXTERNAL_SESSION_TOOL_HANDLERS = {
    "session_ingest": mcp_session_ingest,
    "approval_request": mcp_approval_request,
}


async def active_mcp_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="MCP OAuth user is not active")
    return user


async def _record_success(
    db: AsyncSession,
    ctx: Context | None,
    *,
    user: User,
    grant_id: str | None,
    api_key_project_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    audit_arguments: dict[str, Any],
    audit_result: Any,
) -> None:
    await record_mcp_tool_activity(
        db,
        user=user,
        grant_id=grant_id,
        client_name=mcp_client_name(ctx),
        tool_name=tool_name,
        arguments=arguments,
    )
    await audit_mcp_knowledge_tool_call(
        db,
        user_id=user.id,
        api_key_id=grant_id,
        api_key_project_id=api_key_project_id,
        tool_name=tool_name,
        arguments=audit_arguments,
        result=audit_result,
        status_value="success",
        transport="mcp",
    )
    await db.commit()


async def run_external_session_tool(
    db: AsyncSession, ctx: Context | None, *, user_id: str, grant_id: str | None, tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    user = await active_mcp_user(db, user_id)
    await enforce_mcp_knowledge_rate_limit(api_key_id=grant_id, user_id=user_id, tool_name=tool_name)
    result = await _EXTERNAL_SESSION_TOOL_HANDLERS[tool_name](
        db, user=user, grant_id=grant_id, arguments=arguments
    )
    await _record_success(db, ctx, user=user, grant_id=grant_id, api_key_project_id=None, tool_name=tool_name,
                          arguments=arguments, audit_arguments={"project_id": arguments.get("project_id")},
                          audit_result={"status": result.get("status")})
    return result


async def run_entity_graph_tool(
    db: AsyncSession, ctx: Context | None, *, user_id: str, grant_id: str | None, tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    user = await active_mcp_user(db, user_id)
    await enforce_mcp_knowledge_rate_limit(api_key_id=grant_id, user_id=user_id, tool_name=tool_name)
    # Graph descriptions are extracted from synced sources: fenced as untrusted data, like the chat's reads.
    result = fence_knowledge_result(
        tool_name, await GRAPH_TOOL_HANDLERS[tool_name](db, user=user, arguments=arguments))
    await _record_success(db, ctx, user=user, grant_id=grant_id, api_key_project_id=None, tool_name=tool_name,
                          arguments=arguments, audit_arguments=arguments, audit_result={"status": "ok"})
    return result


