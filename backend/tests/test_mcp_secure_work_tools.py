from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, User, WorkItem
from app.services import mcp_secure_work_tools as work_tools
from app.services import mcp_work_item_listing
from app.services.mcp_secure_work_tools import MCP_SECURE_WORK_TOOL_HANDLERS
from app.services.mcp_work_access import build_work_grant_scope
from app.services.secure_work.platform_items import create_platform_work_item


def _with_unrestricted_grant(handler):
    """Call an MCP handler as the dispatcher does for a grant without project binding."""

    async def call(db, *, user, arguments):
        scope = await build_work_grant_scope(db, user=user, grant_id=None, binding=None)
        return await handler(db, user=user, scope=scope, arguments=arguments)

    return call


mcp_work_item_find = _with_unrestricted_grant(work_tools.mcp_work_item_find)
mcp_work_item_list = _with_unrestricted_grant(mcp_work_item_listing.mcp_work_item_list)
mcp_work_item_transition = _with_unrestricted_grant(work_tools.mcp_work_item_transition)


async def _fixture(db):
    user = User(username="mcp-work-user", email="mcp-work@example.test", password_hash="x")
    db.add(user)
    item = WorkItem(
        source_type="jira",
        source_instance="mcp-test",
        source_key="OCX-MCP-1",
        title="MCP secure work test",
        source_status="Requested",
        work_state="intake",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    return user, item


async def test_work_item_find_by_key_and_id(db):
    _user, item = await _fixture(db)
    # The fixture item has no workspace, which find serves to a platform admin only.
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    by_key = await mcp_work_item_find(db, user=user, arguments={"work_item": "OCX-MCP-1"})
    assert by_key["id"] == item.id and by_key["work_state"] == "intake"
    by_id = await mcp_work_item_find(db, user=user, arguments={"work_item": item.id})
    assert by_id["source_key"] == "OCX-MCP-1"
    with pytest.raises(HTTPException) as exc:
        await mcp_work_item_find(db, user=user, arguments={"work_item": "OCX-DOES-NOT-EXIST"})
    assert exc.value.status_code == 404


async def test_transition_requires_a_configured_workflow(db):
    _user, item = await _fixture(db)
    # Transition needs the work-operator role and the item has no workspace: the seeded admin.
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    with pytest.raises(HTTPException) as exc:
        await mcp_work_item_transition(
            db, user=user, arguments={"work_item": item.source_key, "to_state": "development"}
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_work_item_list_returns_open_items_with_readiness(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    open_item = await create_platform_work_item(
        db, current_user=admin, project_id=project.id, title="Open task to pick up"
    )
    done_item = await create_platform_work_item(
        db, current_user=admin, project_id=project.id, title="Already finished"
    )
    done_item.work_state = "done"
    await db.flush()

    result = await mcp_work_item_list(
        db, user=admin, arguments={"project_id": project.id, "source_type": "platform", "limit": 100}
    )
    keys = {it["source_key"] for it in result["items"]}
    assert open_item.source_key in keys       # open item is listed
    assert done_item.source_key not in keys    # terminal state excluded
    assert result["filter_state"] == "open"
    row = next(it for it in result["items"] if it["source_key"] == open_item.source_key)
    assert set(row) >= {"work_state", "priority", "has_plan", "sessions", "assignee"}

    # explicit state filter
    only_intake = await mcp_work_item_list(
        db, user=admin, arguments={"project_id": project.id, "state": "intake", "source_type": "platform"}
    )
    assert all(it["work_state"] == "intake" for it in only_intake["items"])


def test_tool_family_is_complete():
    assert set(MCP_SECURE_WORK_TOOL_HANDLERS) == {
        "work_item_find",
        "work_item_list",
        "work_item_create",
        "work_item_context",
        "work_item_link_session",
        "work_item_note",
        "change_units_plan",
        "change_plan_generate",
        "change_plan_decide",
        "work_item_redeclare",
        "coding_agent_start",
        "work_item_transition",
        "coding_observability",
    }
