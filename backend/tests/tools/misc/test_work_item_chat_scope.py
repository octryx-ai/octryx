"""Security: the chat work-item tools enforce the caller's Workspace scope exactly like MCP."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, User, UserProject, WorkItem
from app.services.mcp_work_access import build_work_grant_scope, scoped_work_item
from app.tools.context import ToolContext
from app.tools.secure_work_impl._work_item_tools import (
    WorkItemContextTool,
    WorkItemCreateTool,
    WorkItemLinkSessionTool,
    WorkItemNoteTool,
)
from tests.tools.jira_impl.test_jira_task_list_governance import _operator


async def _workspaces(db):
    a, b = (Project(name=f"{name}-{uuid.uuid4().hex[:6]}", config={}) for name in ("a", "b"))
    db.add_all([a, b])
    await db.flush()
    item_a = WorkItem(project_id=a.id, source_type="platform", source_key=f"A-{uuid.uuid4().hex[:6]}", title="A")
    item_b = WorkItem(project_id=b.id, source_type="platform", source_key=f"B-{uuid.uuid4().hex[:6]}", title="B")
    shared_key = f"DUP-{uuid.uuid4().hex[:6]}"
    dup_a = WorkItem(project_id=a.id, source_type="jira", source_instance="a", source_key=shared_key, title="dup A")
    dup_b = WorkItem(project_id=b.id, source_type="jira", source_instance="b", source_key=shared_key, title="dup B")
    db.add_all([item_a, item_b, dup_a, dup_b])
    member = await _operator(db)
    db.add(UserProject(user_id=member.id, project_id=a.id, role="member"))
    await db.commit()
    return a, b, member, item_a, item_b, dup_a


def _context(user: User, *projects: str) -> ToolContext:
    return ToolContext(user_id=user.id, project_ids=list(projects), roles=[], session_id="s", project_config={})


TOOLS = {
    "context": lambda value: (WorkItemContextTool(), {"work_item": value}),
    "note": lambda value: (WorkItemNoteTool(), {"work_item": value, "note": "should not land"}),
    "link_session": lambda value: (WorkItemLinkSessionTool(), {"work_item": value, "client_session_id": "c-1"}),
}


@pytest.mark.parametrize("tool", sorted(TOOLS))
@pytest.mark.parametrize("by", ["id", "key"])
async def test_a_member_of_a_cannot_reach_bs_item_by_id_or_key(db, tool, by):
    a, _b, member, _item_a, item_b, _dup = await _workspaces(db)
    context = _context(member, a.id)
    context.db = db
    instance, params = TOOLS[tool](item_b.id if by == "id" else item_b.source_key)
    result = await instance.execute(params, context)
    value = item_b.id if by == "id" else item_b.source_key
    assert result == {"error": f"Work item not found: {value}", "status_code": 404}, "the same answer as missing"
    await db.refresh(item_b)
    assert "platform_notes" not in (item_b.source_fields_json or {})
    missing = await instance.execute(TOOLS[tool]("NOPE-404")[1], context)
    assert missing["status_code"] == 404 and missing["error"] == "Work item not found: NOPE-404"


async def test_own_items_still_work_and_a_shared_key_resolves_to_the_own_one(db):
    a, _b, member, item_a, _item_b, dup_a = await _workspaces(db)
    context = _context(member, a.id)
    context.db = db
    assert (await WorkItemContextTool().execute({"work_item": item_a.id}, context))["work_item"]["id"] == item_a.id
    note = await WorkItemNoteTool().execute({"work_item": item_a.source_key, "note": "own"}, context)
    assert note == {"work_item": item_a.source_key, "notes": 1}
    shared = await WorkItemContextTool().execute({"work_item": dup_a.source_key}, context)
    assert shared["work_item"]["id"] == dup_a.id


async def test_creating_in_another_workspace_is_refused(db):
    a, b, member, *_rest = await _workspaces(db)
    context = _context(member, a.id)
    context.db = db
    refused = await WorkItemCreateTool().execute({"title": "x", "project_id": b.id}, context)
    assert refused["status_code"] == 403
    assert (await db.execute(select(WorkItem).where(WorkItem.project_id == b.id, WorkItem.title == "x"))).first() is None
    own = await WorkItemCreateTool().execute({"title": "mine"}, context)
    assert own["project_id"] == a.id


async def test_an_invented_project_id_creates_in_the_chats_own_workspace(db):
    a, _b, member, *_rest = await _workspaces(db)
    context = _context(member, a.id)
    context.db = db
    created = await WorkItemCreateTool().execute({"title": "invented", "project_id": "packmate-workspace"}, context)
    assert created["project_id"] == a.id


async def test_creating_the_same_open_item_again_returns_it_instead_of_a_duplicate(db):
    a, _b, member, *_rest = await _workspaces(db)
    context = _context(member, a.id)
    context.db = db
    first = await WorkItemCreateTool().execute({"title": "Packmate T1", "description": "x"}, context)
    again = await WorkItemCreateTool().execute({"title": "Packmate T1", "description": "y"}, context)
    assert again["source_key"] == first["source_key"] and again["already_existed"] is True
    other = await WorkItemCreateTool().execute({"title": "Packmate T2"}, context)
    assert other["source_key"] != first["source_key"] and "already_existed" not in other


async def test_the_session_workspaces_narrow_even_a_member_of_both(db):
    a, b, member, _item_a, item_b, _dup = await _workspaces(db)
    db.add(UserProject(user_id=member.id, project_id=b.id, role="member"))
    await db.commit()
    in_a = _context(member, a.id)
    in_a.db = db
    assert (await WorkItemContextTool().execute({"work_item": item_b.id}, in_a))["status_code"] == 404
    in_b = _context(member, b.id)
    in_b.db = db
    assert (await WorkItemContextTool().execute({"work_item": item_b.id}, in_b))["work_item"]["id"] == item_b.id
    assert (await WorkItemCreateTool().execute({"title": "y", "project_id": b.id}, in_a))["status_code"] == 403
    assert (await WorkItemCreateTool().execute({"title": "y", "project_id": b.id}, in_b))["project_id"] == b.id


async def test_a_platform_admin_is_bound_by_the_session_and_unrestricted_without_one(db):
    a, _b, _member, _item_a, item_b, _dup = await _workspaces(db)
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    bound = _context(admin, a.id)
    bound.db = db
    assert (await WorkItemContextTool().execute({"work_item": item_b.id}, bound))["status_code"] == 404
    unbound = _context(admin)
    unbound.db = db
    assert (await WorkItemContextTool().execute({"work_item": item_b.id}, unbound))["work_item"]["id"] == item_b.id


async def test_the_mcp_boundary_answers_the_same_for_the_same_member(db):
    from fastapi import HTTPException

    a, _b, member, _item_a, item_b, _dup = await _workspaces(db)
    scope = await build_work_grant_scope(db, user=member, grant_id=None, binding=frozenset({a.id}))
    for value in (item_b.id, item_b.source_key):
        with pytest.raises(HTTPException) as refused:
            await scoped_work_item(db, scope, value)
        assert refused.value.status_code == 404
