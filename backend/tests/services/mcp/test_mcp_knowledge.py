"""Knowledge MCP surface tests: OAuth-only auth on REST and native transports."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Project
from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_knowledge_observability
from app.services.mcp_governed_knowledge import WORKSPACE_HEADER
from app.time_utils import utc_now
from tests.support.oauth_test_utils import obtain_oauth_tokens


def _bearer(tokens: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _grant_of(db: AsyncSession, tokens: dict) -> OAuthGrant:
    return (
        await db.execute(select(OAuthGrant).where(OAuthGrant.client_id == tokens["client_id"]))
    ).scalar_one()


@pytest.mark.asyncio
async def test_mcp_knowledge_requires_oauth_bearer(client, auth_headers):
    # A platform JWT is not an OAuth access token and must be rejected.
    response = await client.get("/api/v1/mcp/knowledge/tools", headers=auth_headers)
    assert response.status_code == 401
    assert "OAuth token is invalid" in response.text

    # No credentials at all.
    anonymous = await client.get("/api/v1/mcp/knowledge/tools")
    assert anonymous.status_code == 401
    assert "OAuth Bearer" in anonymous.text


@pytest.mark.asyncio
async def test_mcp_knowledge_rejects_missing_knowledge_scope(client, db):
    tokens = await obtain_oauth_tokens(client, scope="read")

    response = await client.get("/api/v1/mcp/knowledge/tools", headers=_bearer(tokens))

    assert response.status_code == 403
    assert "knowledge:read" in response.text


@pytest.mark.asyncio
async def test_mcp_knowledge_lists_tools_with_oauth_token(client, db):
    tokens = await obtain_oauth_tokens(client)

    response = await client.get("/api/v1/mcp/knowledge/tools", headers=_bearer(tokens))

    assert response.status_code == 200, response.text
    names = {tool["name"] for tool in response.json()["tools"]}
    assert "knowledge_search" in names


@pytest.mark.asyncio
async def test_mcp_knowledge_http_tool_call_writes_bounded_audit(client, db):
    mcp_knowledge_observability.clear_mcp_knowledge_observability_state()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    tokens = await obtain_oauth_tokens(client)

    # The unbound grant without a Workspace header answers the fixed needs_configuration state.
    response = await client.post(
        "/api/v1/mcp/knowledge/tools/knowledge_search",
        headers=_bearer(tokens),
        json={"arguments": {"project_id": project.id, "query": "x" * 800}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"]["state"] == "needs_configuration"
    audit = (
        (
            await db.execute(
                select(AuditLog)
                .where(
                    AuditLog.resource_type == "mcp_knowledge",
                    AuditLog.action == "MCP knowledge tool knowledge_search",
                )
                .order_by(AuditLog.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.details["transport"] == "http"
    assert audit.details["status"] == "needs_configuration"
    # The governed tools audit the Workspace only: no argument (not the query, not a model project_id).
    assert "query" not in audit.details["arguments"] and "x" * 300 not in str(audit.details)
    assert tokens["access_token"] not in str(audit.details)
    assert tokens["refresh_token"] not in str(audit.details)


@pytest.mark.asyncio
async def test_mcp_knowledge_http_tool_call_is_rate_limited(client, db, monkeypatch):
    mcp_knowledge_observability.clear_mcp_knowledge_observability_state()
    monkeypatch.setattr(mcp_knowledge_observability, "MCP_KNOWLEDGE_RATE_LIMIT_MAX_REQUESTS", 1)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    tokens = await obtain_oauth_tokens(client)
    payload = {"arguments": {"project_id": project.id, "query": "deployment", "layers": ["gold"], "limit": 1}}

    first = await client.post(
        "/api/v1/mcp/knowledge/tools/knowledge_search", headers=_bearer(tokens), json=payload
    )
    second = await client.post(
        "/api/v1/mcp/knowledge/tools/knowledge_search", headers=_bearer(tokens), json=payload
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.headers["Retry-After"]
    metrics = mcp_knowledge_observability.render_mcp_knowledge_metrics()
    assert any('tool="knowledge_search",status="rate_limited"' in line for line in metrics)


@pytest.mark.asyncio
async def test_mcp_knowledge_project_bound_grant_rejects_other_project(client, db):
    projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    if len(projects) < 2:
        other = Project(id=str(uuid.uuid4()), name="mcp-other-project", config={}, is_active=True)
        db.add(other)
        await db.commit()
        projects = (await db.execute(select(Project).order_by(Project.name.asc()))).scalars().all()
    bound_project = projects[0]
    other_project = next(project for project in projects if project.id != bound_project.id)
    tokens = await obtain_oauth_tokens(client)
    grant = await _grant_of(db, tokens)
    grant.project_ids = [bound_project.id]
    await db.commit()
    # A Workspace header outside the grant's binding is refused as not_found (the model's project_id
    # argument is never scope input).
    response = await client.post(
        "/api/v1/mcp/knowledge/tools/knowledge_search",
        headers={**_bearer(tokens), WORKSPACE_HEADER: other_project.id},
        json={"arguments": {"project_id": other_project.id, "query": "deployment"}},
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"]["state"] == "not_found"


@pytest.mark.asyncio
async def test_mcp_knowledge_revoked_grant_is_rejected_immediately(client, db):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    tokens = await obtain_oauth_tokens(client)
    grant = await _grant_of(db, tokens)
    grant.revoked_at = utc_now()
    await db.commit()

    response = await client.post(
        "/api/v1/mcp/knowledge/tools/knowledge_search",
        headers=_bearer(tokens),
        json={"arguments": {"project_id": project.id, "query": "deployment"}},
    )

    assert response.status_code == 401
    assert "grant is revoked" in response.text
