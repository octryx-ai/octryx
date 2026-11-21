from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, User
from app.services.flow_node_catalog import build_flow_node_catalog
from app.services.tool_config import upsert_tool_config
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def _items_by_ref(payload: dict) -> dict[str, dict]:
    return {str(item["binding_ref"]): item for item in payload["items"]}


@pytest.mark.asyncio
async def test_flow_node_catalog_honors_read_pattern_project_policy(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    demo.config = {"tool_policy": {"allow_patterns": ["read_*"]}}
    await upsert_tool_config(db, tool_name="system", project_id=None, config={}, is_active=True)
    await upsert_tool_config(db, tool_name="system", project_id=demo.id, config={}, is_active=True)
    await db.flush()

    payload = await build_flow_node_catalog(db, project_id=demo.id, current_user=admin)
    items = _items_by_ref(payload)

    assert items["read_workspace_file"]["availability_status"] == "available"
    assert items["knowledge_search"]["availability_status"] == "disabled"
    assert items["knowledge_search"]["disabled_reason"] == "Not included in the project tool visibility allow rules."


@pytest.mark.asyncio
async def test_flow_node_catalog_honors_exact_project_allowlist(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    demo.config = {"tool_policy": {"allowlist": ["knowledge_search"]}}
    await upsert_tool_config(db, tool_name="system", project_id=None, config={}, is_active=True)
    await upsert_tool_config(db, tool_name="system", project_id=demo.id, config={}, is_active=True)
    await db.flush()

    payload = await build_flow_node_catalog(db, project_id=demo.id, current_user=admin)
    items = _items_by_ref(payload)

    assert items["knowledge_search"]["availability_status"] == "available"
    assert items["read_workspace_file"]["availability_status"] == "disabled"
    assert items["read_workspace_file"]["disabled_reason"] == "Not included in the project tool visibility allow rules."


@pytest.mark.asyncio
async def test_flow_node_catalog_explains_ungranted_connector(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    await upsert_tool_config(
        db,
        tool_name="jira",
        project_id=None,
        config={
            "jira_url": "https://jira.example.com",
            "jira_allowed_projects": ["RIVER"],
        },
        is_active=True,
    )
    await db.flush()

    payload = await build_flow_node_catalog(db, project_id=demo.id, current_user=admin)
    jira_tool = _items_by_ref(payload)["search_jira_tickets"]

    assert jira_tool["availability_status"] == "disabled"
    assert jira_tool["disabled_reason"] == "jira connector is configured globally but not granted to this project."


@pytest.mark.asyncio
async def test_disabled_tool_runtime_fails_with_clear_project_policy_error(db):
    demo = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    project_config = {"tool_policy": {"allowlist": ["knowledge_search"]}}
    context = ToolContext(
        db=db,
        project_ids=[demo.id],
        roles=["admin"],
        project_config=project_config,
        user_id="test-user",
        session_id="test-session",
    )

    result = await execute_tool("read_workspace_file", {"path": "README.md"}, context)

    assert result["error"] == "Not included in the project tool visibility allow rules."
    assert result["tool_name"] == "read_workspace_file"
    assert result["policy"] == "project_tool_policy"
