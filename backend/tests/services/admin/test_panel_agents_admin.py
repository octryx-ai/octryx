"""Tests for panel agent management: MCP servers, agent builder, seeded agents, and bootstrap preselection."""

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Project


@pytest.mark.asyncio
async def test_admin_panel_mcp_servers_endpoint_renders_without_import_error(admin_client, db):
    workspace = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    mcp_resp = await admin_client.get(
        "/admin/chat/api/panel/mcp/servers",
        params={"workspace_id": workspace.id},
    )
    assert mcp_resp.status_code == 200
    assert isinstance(mcp_resp.json(), list)


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_agent_builder_endpoints_return_full_payload(admin_client):
    meta_resp = await admin_client.get("/admin/chat/api/panel/agents/meta")
    assert meta_resp.status_code == 200
    meta_payload = meta_resp.json()
    assert "agent_template_choices" not in meta_payload
    assert "tool_options" in meta_payload
    assert "agent_modes" in meta_payload

    create_resp = await admin_client.post(
        "/admin/chat/api/panel/agents",
        json={
            "name": "Panel Agent",
            "description": "Managed from panel",
            "goal": "Explain health checks",
            "agent_type": "diagnosis",
            "thinking_level": "light",
            "branch_prefix": "octryx",
            "is_active": True,
        },
    )
    assert create_resp.status_code == 200
    agent_payload = create_resp.json()
    assert agent_payload["name"] == "Panel Agent"
    assert agent_payload["steps"] == []

    step_resp = await admin_client.post(
        f"/admin/chat/api/panel/agents/{agent_payload['id']}/steps",
        json={
            "name": "Search docs",
            "step_type": "knowledge",
            "instructions": "Use the knowledge map first",
            "success_criteria": "Relevant documentation found",
            "allowed_tools": ["list_project_knowledge", "get_confluence_page"],
            "is_enabled": True,
        },
    )
    assert step_resp.status_code == 200
    step_payload = step_resp.json()
    assert step_payload["name"] == "Search docs"

    list_resp = await admin_client.get("/admin/chat/api/panel/agents")
    assert list_resp.status_code == 200
    agents = list_resp.json()
    created = next(agent for agent in agents if agent["id"] == agent_payload["id"])
    assert created["steps"][0]["allowedTools"] == ["list_project_knowledge", "get_confluence_page"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_agents_includes_seeded_acme_orders_agents(admin_client):
    list_resp = await admin_client.get("/admin/chat/api/panel/agents")
    assert list_resp.status_code == 200
    names = {agent["name"] for agent in list_resp.json()}
    assert "Document Updater" in names


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_chat_bootstrap_preselects_seeded_agent_from_query(admin_client, db):
    agent = (
        await db.execute(
            select(AgentDefinition).where(AgentDefinition.name == "Document Updater")
        )
    ).scalar_one()

    resp = await admin_client.get(f"/admin/chat/api/bootstrap?new=true&agent_id={agent.id}")
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["newThread"] is True
    assert payload["selectedAgentId"] == agent.id
    assert payload["selectedAgentName"] == "Document Updater"
    assert payload["selectedProjectId"]
    assert payload["selectedThinkingLevel"] == "deep"
    assert payload["selectedAgentType"] == "change"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_panel_seeded_agent_payload_exposes_its_steps_and_no_execution_mode(admin_client, db):
    list_resp = await admin_client.get("/admin/chat/api/panel/agents")
    assert list_resp.status_code == 200
    agents = {agent["name"]: agent for agent in list_resp.json()}

    assert "executionMode" not in agents["Document Updater"]
    assert [step["stepType"] for step in agents["Document Updater"]["steps"]] == [
        "analysis",
        "documentation",
        "change",
    ]
