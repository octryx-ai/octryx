"""Shared helpers for the test_mcp_claude_code_parity_* modules."""

from __future__ import annotations

from app.services import (
    mcp_extra_registration,
    mcp_governed_knowledge_tools,
    mcp_knowledge_ledger_tools,
    mcp_knowledge_protocol,
    mcp_parity_registration,
)
from app.services.agent_gateway.identity import GatewayIdentity
from app.services.agent_gateway.sessions import get_or_create_gateway_session
from app.services.mcp_governed_knowledge import McpCaller
from tests.knowledge_evidence_seed_support import fetch_user
from tests.mcp_native_support import session_factory

SCOPES = ("knowledge:read", "knowledge:write", "workflow:read", "workflow:execute", "sessions:read")


def _caller(user_id: str, workspace_id: str | None, **overrides) -> McpCaller:
    values = {"user_id": user_id, "grant_id": f"grant-{user_id[:8]}", "scopes": SCOPES,
              "workspace_header": workspace_id, "client_name": "claude-code"}
    values.update(overrides)
    return McpCaller(**values)


def _native(db, monkeypatch):
    factory = session_factory(db)
    for module in (mcp_knowledge_protocol, mcp_governed_knowledge_tools, mcp_knowledge_ledger_tools,
                   mcp_parity_registration, mcp_extra_registration):
        monkeypatch.setattr(module, "async_session_factory", factory)


async def _gateway_session(db, user_id: str, workspace_id: str, session_key: str):
    identity = GatewayIdentity(
        user=await fetch_user(db, user_id), grant_id="gw-grant", oauth_client_id="octryx", workspace_id=workspace_id,
        session_key=session_key, work_item_key="",
    )
    return await get_or_create_gateway_session(db, identity)
