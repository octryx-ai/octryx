"""External-session ingest tests: usage return, approvals and the session graph ingest."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Session, UsageEvent, User
from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_knowledge_protocol
from app.services.oauth_provider import mint_access_token
from tests.mcp_knowledge_support import _call_native_mcp_tool, _native_mcp_session_factory


async def _token(db: AsyncSession, scopes: list[str]) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_ext_{uuid.uuid4().hex[:6]}", scopes=scopes)
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id, client_id=grant.client_id, grant_id=grant.id, scopes=scopes, resource=None
    )
    return token


@pytest.mark.asyncio
async def test_session_ingest_creates_shadow_session_and_usage_events(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["session:write"])

    result = await _call_native_mcp_tool(
        token,
        "session_ingest",
        {
            "project_id": project.id,
            "summary": "Refactored the services layer; retired 71 shims.",
            "usage": [
                {"model": "claude-sonnet-5", "input_tokens": 120000, "output_tokens": 30000},
                {"model": "claude-haiku-4-5", "input_tokens": 20000, "output_tokens": 4000},
            ],
            "workspace_ref": "octryx@codex/epic-coding-runtime-execution-core",
            "client": "claude_code",
        },
    )

    assert not result.isError, result.content
    payload = result.structuredContent
    assert payload["status"] == "ingested"
    assert payload["usage_events"] == 2

    session = await db.get(Session, payload["external_session_id"])
    assert session is not None
    assert session.agent_type == "external_agent"
    assert session.metadata_["external_source"] == "claude_code"

    events = (
        (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    )
    assert len(events) == 2
    assert {event.provider for event in events} == {"claude_code"}
    assert sum(event.tokens_in for event in events) == 140000


@pytest.mark.asyncio
async def test_session_ingest_provider_reflects_the_real_client(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["session:write"])

    # A Codex session must NOT be tagged as claude_code - the client is derived
    # from the client_session_id prefix even without an explicit field.
    result = await _call_native_mcp_tool(
        token,
        "session_ingest",
        {
            "project_id": project.id,
            "summary": "Codex run",
            "usage": [{"model": "gpt-5.5", "input_tokens": 1000, "output_tokens": 200}],
            "client_session_id": "codex-abc123",
        },
    )
    assert not result.isError, result.content
    session = await db.get(Session, result.structuredContent["external_session_id"])
    assert session.metadata_["external_source"] == "codex"
    events = (
        (await db.execute(select(UsageEvent).where(UsageEvent.session_id == session.id))).scalars().all()
    )
    assert {event.provider for event in events} == {"codex"}


@pytest.mark.asyncio
async def test_session_ingest_requires_session_write_scope(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["knowledge:read"])

    result = await _call_native_mcp_tool(token, "session_ingest", {"project_id": project.id})

    assert result.isError
    assert "session:write" in str(result.content)


@pytest.mark.asyncio
async def test_approval_request_creates_pending_approval(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["write", "read"])

    result = await _call_native_mcp_tool(
        token,
        "approval_request",
        {"project_id": project.id, "action": "run_terraform_apply_prod", "reason": "Release rollout"},
    )

    assert not result.isError, result.content
    payload = result.structuredContent
    assert payload["status"] == "pending"

    from app.models import Approval

    approval = await db.get(Approval, payload["approval_id"])
    assert approval is not None
    assert approval.action == "run_terraform_apply_prod"
    assert approval.session_id == payload["external_session_id"]

    listed = await _call_native_mcp_tool(token, "approval_list", {"status": "pending"})
    assert not listed.isError
    assert any(item["id"] == payload["approval_id"] for item in listed.structuredContent["items"])


@pytest.mark.asyncio
async def test_approval_request_requires_write_scope(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["read"])

    result = await _call_native_mcp_tool(
        token, "approval_request", {"project_id": project.id, "action": "x"}
    )

    assert result.isError
    assert "write" in str(result.content)


@pytest.mark.asyncio
async def test_session_ingest_with_digest_feeds_the_knowledge_graph(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token(db, ["session:write"])
    client_session_id = f"claude-code-{uuid.uuid4().hex[:8]}"

    result = await _call_native_mcp_tool(
        token,
        "session_ingest",
        {
            "project_id": project.id,
            "summary": "Fixed the Jira sync regression.",
            "usage": [{"model": "claude-sonnet-5", "input_tokens": 1000, "output_tokens": 200}],
            "workspace_ref": "/srv/octryx",
            "client_session_id": client_session_id,
            "transcript_digest": "[USER] fix the jira sync\n\n[ASSISTANT] Fixed jira_state_sync guard.",
        },
    )

    assert not result.isError, result.content
    payload = result.structuredContent
    # No KnowledgeMap digest copy: the graph references the shadow session itself.
    assert "knowledge_entry_id" not in payload
    graph = payload["knowledge_graph"]
    assert graph is not None
    # Deterministic record always lands; LLM extraction reports itself
    # honestly when no EXTRACT runtime is configured in the test env.
    assert graph["graph_entities"] >= 1
    assert graph["extraction"] in {"completed", "unavailable", "failed"}

    from app.models import KnowledgeGraphEdge, KnowledgeGraphNode

    session_node = (
        await db.execute(
            select(KnowledgeGraphNode).where(
                KnowledgeGraphNode.node_type == "agent_session",
                KnowledgeGraphNode.node_key == f"agent-session-{client_session_id}",
            )
        )
    ).scalar_one()
    assert session_node.source_refs == [f"agent-session:{payload['external_session_id']}"]
    person_edge = (
        await db.execute(
            select(KnowledgeGraphEdge).where(
                KnowledgeGraphEdge.target_node_id == session_node.id,
                KnowledgeGraphEdge.edge_type == "contributed_to",
            )
        )
    ).scalar_one()
    person = await db.get(KnowledgeGraphNode, person_edge.source_node_id)
    assert person is not None and person.node_type == "person"
