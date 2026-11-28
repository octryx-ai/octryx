"""Read-only external Knowledge MCP tool endpoints (OAuth bearer auth)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ....db import get_db
from ....models import User
from ....services.data_access import bind_request_viewer
from ....services.mcp_extra_tools import EXTRA_GOVERNED_MCP_TOOLS
from ....services.mcp_governed_knowledge import SESSION_HEADER, WORKSPACE_HEADER, McpCaller, run_governed_mcp_tool
from ....services.mcp_knowledge_observability import audit_mcp_knowledge_tool_call
from ....services.mcp_parity_dispatch import PARITY_MCP_TOOLS, run_parity_mcp_tool
from ....services.oauth_provider import OAuthResourceContext, acceptable_mcp_audiences, resolve_oauth_resource_context
from ....services.work_item_analysis.seat_mcp_gate import (
    analysis_tool_refusal,
    pinned_analysis,
    record_server_evidence,
    result_is_error,
)

router = APIRouter(prefix="/api/v1/mcp/knowledge", tags=["mcp-knowledge"])

SUPPORTED_KNOWLEDGE_MCP_TOOLS = {
    "knowledge_search": {
        "description": "Search the Workspace's governed Knowledge; every passage carries its cite_as source link.",
        "required_scopes": ["knowledge:read"],
    },
    "knowledge_read": {
        "description": "Read a cited source of the Workspace's governed Knowledge by its reference.",
        "required_scopes": ["knowledge:read"],
    },
    "knowledge_changes": {
        "description": "List the typed, cited change facts of one product up to a version.",
        "required_scopes": ["knowledge:read"],
    },
    "jira_release_status": {
        "description": "Query Jira live (read-only) for the status of one product release.",
        "required_scopes": ["knowledge:read"],
    },
    "knowledge_code_impact": {
        "description": "Where a product version change applies in this codebase, cited, with file:line links.",
        "required_scopes": ["knowledge:read"],
    },
    **{
        name: {"description": f"Governed {name.replace('_', ' ')}.", "required_scopes": ["knowledge:read", scope]}
        for name, (_handler, scope) in PARITY_MCP_TOOLS.items()
    },
    **{
        name: {"description": f"Governed {name.replace('_', ' ')} (the chat tool).", "required_scopes": [scope]}
        for name, (_tool, scope) in EXTRA_GOVERNED_MCP_TOOLS.items()
    },
}


class KnowledgeMcpToolRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("/tools")
async def list_knowledge_mcp_tools(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    context = await _require_oauth_context(request, db)
    current_user = await _require_active_user(db, context)
    return {
        "server": "octryx-knowledge",
        "transport": "streamable-http",
        "tools": [
            {"name": name, **metadata}
            for name, metadata in sorted(SUPPORTED_KNOWLEDGE_MCP_TOOLS.items(), key=lambda item: item[0])
        ],
        "user_id": current_user.id,
    }


@router.post("/tools/{tool_name}")
async def call_knowledge_mcp_tool(
    tool_name: str,
    payload: KnowledgeMcpToolRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    context = await _require_oauth_context(request, db)
    # The governed runner re-checks the user; this keeps the early 401 for an inactive grant owner.
    await _require_active_user(db, context)
    if tool_name not in SUPPORTED_KNOWLEDGE_MCP_TOOLS:
        raise HTTPException(status_code=404, detail="Unknown Knowledge MCP tool")
    return await _call_governed_tool(db, request, context, tool_name=tool_name, arguments=payload.arguments)


async def _call_governed_tool(
    db: AsyncSession, request: Request, context: OAuthResourceContext, *, tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    caller = McpCaller(
        user_id=context.user_id,
        grant_id=context.grant_id,
        scopes=tuple(context.scopes),
        bound_project_ids=tuple(context.bound_project_ids or ()),
        workspace_header=request.headers.get(WORKSPACE_HEADER),
        client_name="mcp-http",
        transport="http",
        session_key=request.headers.get(SESSION_HEADER),
    )
    # A seat analysis session runs only its analysis tools; its read tool runs are its evidence (seat_mcp_gate).
    pinned = await pinned_analysis(db, caller.session_key)
    refusal = analysis_tool_refusal(pinned, tool_name)
    if refusal is None:
        from ....services.agent_tools_deny import run_session_mcp_refusal

        refusal = await run_session_mcp_refusal(db, caller.session_key, tool_name)  # the run phase's deny
    if refusal is not None:
        return {"tool": tool_name, "result": refusal}
    runner = run_parity_mcp_tool if tool_name in PARITY_MCP_TOOLS else run_governed_mcp_tool
    try:
        result = await runner(db, caller=caller, tool_name=tool_name, arguments=dict(arguments))
    except HTTPException as exc:
        if exc.status_code == 429:
            await audit_mcp_knowledge_tool_call(
                db,
                user_id=context.user_id,
                api_key_id=context.grant_id,
                api_key_project_id=",".join(context.bound_project_ids or ()) or None,
                tool_name=tool_name,
                arguments={},
                status_value="rate_limited",
                transport="http",
            )
            await db.commit()
        raise
    record_server_evidence(db, pinned, user_id=context.user_id, tool_name=tool_name,
                           text=json.dumps(result, ensure_ascii=False, default=str),
                           is_error=result_is_error(result))
    await db.commit()
    return {"tool": tool_name, "result": result}


async def _require_oauth_context(request: Request, db: AsyncSession) -> OAuthResourceContext:
    authorization = str(request.headers.get("authorization") or "").strip()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Knowledge MCP requires OAuth Bearer authentication",
        )
    from ....services.mcp_knowledge_protocol import KNOWLEDGE_MCP_MOUNT_PATH, KNOWLEDGE_MCP_STREAMABLE_PATH

    audiences = acceptable_mcp_audiences(
        mount_path=KNOWLEDGE_MCP_MOUNT_PATH,
        streamable_path=KNOWLEDGE_MCP_STREAMABLE_PATH,
    )
    context = await resolve_oauth_resource_context(db, token=token.strip(), audiences=audiences)
    if context is not None:
        bind_request_viewer(context.user_id)
    if context is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OAuth token is invalid, expired, or its grant is revoked",
        )
    if not context.has_scope("knowledge:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OAuth grant lacks required scope: knowledge:read",
        )
    return context


async def _require_active_user(db: AsyncSession, context: OAuthResourceContext) -> User:
    user = await db.get(User, context.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OAuth user is not active")
    return user
