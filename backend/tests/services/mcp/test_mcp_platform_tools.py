"""Platform MCP tool-family tests (tasks, approvals, policies) over the native transport."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Approval, Project, Task, User
from app.models.security.oauth_provider import OAuthGrant
from app.services import mcp_knowledge_protocol
from app.services.oauth_provider import mint_access_token
from tests.support.mcp_knowledge_support import _call_native_mcp_tool, _native_mcp_session_factory


async def _token_with_scopes(db: AsyncSession, scopes: list[str], project_ids: list[str] | None = None) -> str:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    grant = OAuthGrant(user_id=admin.id, client_id=f"oec_platform_{uuid.uuid4().hex[:6]}", scopes=scopes,
                       project_ids=project_ids)
    db.add(grant)
    await db.commit()
    token, _ = mint_access_token(
        user_id=admin.id,
        client_id=grant.client_id,
        grant_id=grant.id,
        scopes=scopes,
        resource=None,
    )
    return token


@pytest.mark.asyncio
async def test_task_list_returns_owner_tasks(client, db, monkeypatch, auth_user):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="mcp-platform-task",
        task_type="agent",
        agent_type="generic",
        owner_id=auth_user.id,
        is_active=True,
    )
    db.add(task)
    await db.commit()
    token = await _token_with_scopes(db, ["tasks:read"])

    result = await _call_native_mcp_tool(token, "task_list", {"project_id": project.id})

    assert not result.isError, result.content
    names = [item["name"] for item in result.structuredContent["items"]]
    assert "mcp-platform-task" in names


@pytest.mark.asyncio
async def test_task_list_requires_tasks_read_scope(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    token = await _token_with_scopes(db, ["knowledge:read"])

    result = await _call_native_mcp_tool(token, "task_list", {})

    # A typed refusal that names the missing scope.
    assert result.structuredContent["state"] == "denied"
    assert result.structuredContent["required_scope"] == "tasks:read"


@pytest.mark.asyncio
async def test_task_runs_rejects_foreign_task(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    token = await _token_with_scopes(db, ["tasks:read"])

    result = await _call_native_mcp_tool(token, "task_runs", {"task_id": str(uuid.uuid4())})

    assert result.isError
    assert "Task not found" in str(result.content)


@pytest.mark.asyncio
async def test_approval_list_returns_own_requests(client, db, monkeypatch, auth_user):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    approval = Approval(
        id=str(uuid.uuid4()),
        requested_by=auth_user.id,
        action="run_terraform_apply",
        status="pending",
    )
    db.add(approval)
    await db.commit()
    token = await _token_with_scopes(db, ["read"])

    result = await _call_native_mcp_tool(token, "approval_list", {"status": "pending"})

    assert not result.isError, result.content
    actions = [item["action"] for item in result.structuredContent["items"]]
    assert "run_terraform_apply" in actions


@pytest.mark.asyncio
async def test_policy_effective_reports_governance_summary(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token_with_scopes(db, ["read"])

    result = await _call_native_mcp_tool(token, "policy_effective", {"project_id": project.id})

    assert not result.isError, result.content
    payload = result.structuredContent
    assert payload["project_id"] == project.id
    assert "read_only_tools_enforced" in payload
    assert isinstance(payload["always_deny_patterns"], list)


@pytest.mark.asyncio
async def test_knowledge_tools_enforce_scope_per_tool(client, db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", _native_mcp_session_factory(db))
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    token = await _token_with_scopes(db, ["tasks:read"], [project.id])

    result = await _call_native_mcp_tool(token, "knowledge_read", {"evidence_key": "any"})

    # A governed knowledge tool without knowledge:read answers the explicit denied state.
    assert not result.isError, result.content
    assert result.structuredContent["state"] == "denied"
