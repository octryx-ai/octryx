"""The native MCP transport publishes protected-resource metadata, requires a bearer token and serves the knowledge tools."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User
from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_knowledge_protocol
from app.services.oauth_provider import mint_access_token
from tests.mcp_knowledge_support import (
    _call_native_mcp_tool,
    _initialize_native_mcp,
    _mcp_json_rpc,
    _native_mcp_lifespan,
    _native_mcp_session_factory,
    _NativeMcpTestClient,
)


async def _native_oauth_token(db: AsyncSession) -> str:
    """Mint a real access token backed by a real grant row."""
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    grant = OAuthGrant(user_id=admin.id, client_id="oec_native_test", scopes=["knowledge:read"])
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id,
        client_id="oec_native_test",
        grant_id=grant.id,
        scopes=["knowledge:read"],
        resource=None,
    )
    return token


async def _list_native_mcp_tools(token: str):
    protocol_app = mcp_knowledge_protocol.create_knowledge_mcp_protocol_app()
    async with _native_mcp_lifespan(protocol_app):
        async with _NativeMcpTestClient(
            transport=ASGITransport(app=protocol_app),
            base_url="http://localhost:8000",
            token=token,
        ) as protocol_client:
            await _initialize_native_mcp(protocol_client)
            response = await _mcp_json_rpc(protocol_client, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            return [SimpleNamespace(**tool) for tool in response["result"]["tools"]]


@pytest.mark.asyncio
async def test_protected_resource_metadata_points_at_authorization_server(client, db):
    response = await client.get("/.well-known/oauth-protected-resource")

    assert response.status_code == 200
    body = response.json()
    assert body["resource"].endswith("/api/v1/mcp/knowledge-protocol/mcp")
    assert body["authorization_servers"]


@pytest.mark.asyncio
async def test_protected_resource_metadata_path_suffixed_variant(client, db):
    # RFC 9728: the WWW-Authenticate challenge points a spec-compliant client
    # (VS Code Copilot) at /.well-known/oauth-protected-resource<resource-path>,
    # which must resolve - not just the bare well-known URL.
    challenge = await client.post(
        "/api/v1/mcp/knowledge-protocol/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert challenge.status_code == 401
    header = challenge.headers["www-authenticate"]
    marker = 'resource_metadata="'
    url = header.split(marker, 1)[1].split('"', 1)[0]
    path = url.split("://", 1)[1].split("/", 1)[1]

    response = await client.get(f"/{path}")
    assert response.status_code == 200, response.text
    assert response.json()["resource"].endswith("/api/v1/mcp/knowledge-protocol/mcp")

    assert (await client.get("/.well-known/oauth-protected-resource/nope")).status_code == 404


# ---------------------------------------------------------------------------
# Native Streamable HTTP transport (real OAuth verifier, no monkeypatched auth)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_native_mcp_protocol_requires_bearer_token(client, monkeypatch):
    response = await client.get("/api/v1/mcp/knowledge-protocol/mcp")

    assert response.status_code == 401
    assert "Authentication required" in response.text


@pytest.mark.asyncio
async def test_native_mcp_protocol_lists_knowledge_tools(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    token = await _native_oauth_token(db)

    tools = await _list_native_mcp_tools(token)

    tool_names = {tool.name for tool in tools}
    assert {"knowledge_search", "knowledge_read", "knowledge_changes"}.issubset(tool_names)
    # No KnowledgeMap tools: the ledger tools are the Knowledge tools.
    assert not {
        "knowledge_get",
        "knowledge_graph_neighbors",
        "knowledge_release_status",
        "knowledge_context_bundle",
        "knowledge_propose",
    } & tool_names


@pytest.mark.asyncio
async def test_native_mcp_protocol_serves_knowledge_search_from_the_governed_ledger(client, db, monkeypatch):
    from app.services import mcp_knowledge_ledger_tools

    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    monkeypatch.setattr(mcp_knowledge_ledger_tools, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _native_oauth_token(db)

    # A client that sends project_id and layers: they are ignored, never an input, and the
    # unbound grant without a Workspace header is the explicit needs_configuration state.
    result = await _call_native_mcp_tool(
        token,
        "knowledge_search",
        {"project_id": project.id, "query": "Native MCP Acme Orders deployment", "layers": ["gold"], "limit": 3},
    )

    assert not result.isError, result.content
    payload = result.structuredContent
    assert payload["state"] == "needs_configuration"
    assert "evidence_entries" not in payload


@pytest.mark.asyncio
async def test_native_mcp_protocol_lists_projects(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    token = await _native_oauth_token(db)

    result = await _call_native_mcp_tool(token, "knowledge_projects", {})

    assert not result.isError, result.content
    projects = result.structuredContent["projects"]
    assert any(p["name"] == "acme-orders" for p in projects)
    assert all({"id", "name"} <= set(p) for p in projects)
