"""Calls over the native MCP OAuth path (real token verifier) with connection headers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_knowledge_protocol
from app.services.oauth_provider import mint_access_token


def session_factory(db: AsyncSession):
    return async_sessionmaker(bind=db.bind, class_=AsyncSession, expire_on_commit=False)


async def native_token(db: AsyncSession, *, user_id: str, scopes: list[str], project_ids=None) -> str:
    grant = OAuthGrant(user_id=user_id, client_id="oec_parity_test", scopes=scopes, project_ids=project_ids)
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=user_id, client_id="oec_parity_test", grant_id=grant.id, scopes=scopes, resource=None
    )
    return token


@asynccontextmanager
async def _protocol(token: str, headers: dict[str, str]) -> AsyncIterator[Any]:
    app = mcp_knowledge_protocol.create_knowledge_mcp_protocol_app()
    base = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        **headers,
    }
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:8000") as client:

            async def rpc(payload: dict) -> dict:
                response = await client.post("/mcp", json=payload, headers=base)
                assert response.status_code in {200, 202}, response.text
                return response.json() if response.status_code == 200 else {}

            await rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "claude-code", "version": "test"},
                    },
                }
            )
            await rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
            yield rpc


async def mcp_request(token: str, method: str, params: dict | None = None, headers: dict | None = None) -> dict:
    async with _protocol(token, headers or {}) as rpc:
        response = await rpc({"jsonrpc": "2.0", "id": 2, "method": method, "params": params or {}})
        return response


async def mcp_call(token: str, tool: str, arguments: dict, headers: dict | None = None) -> dict:
    response = await mcp_request(token, "tools/call", {"name": tool, "arguments": arguments}, headers)
    result = response["result"]
    if result.get("isError"):
        return {"isError": True, "content": result.get("content")}
    return result.get("structuredContent") or {}


__all__ = ["mcp_call", "mcp_request", "native_token", "session_factory"]
