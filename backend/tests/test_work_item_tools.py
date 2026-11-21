"""Platform work-item chat tools: same operations as the MCP surface."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project, User
from app.tools.context import ToolContext
from app.tools.secure_work_impl._work_item_tools import WorkItemContextTool, WorkItemCreateTool, WorkItemNoteTool


async def _context(db) -> tuple[ToolContext, User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    context = ToolContext(
        user_id=admin.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="test-session",
        project_config={},
        db=db,
    )
    return context, admin, project


@pytest.mark.asyncio
async def test_chat_agent_creates_epic_task_note_and_reads_context(db):
    context, _admin, project = await _context(db)
    epic = await WorkItemCreateTool().execute(
        {"title": "Chat epic", "issue_type": "epic"}, context
    )
    assert epic["issue_type"] == "epic"
    assert epic["project_id"] == project.id  # session project used as default

    task = await WorkItemCreateTool().execute(
        {"title": "Chat task", "epic_key": epic["source_key"]}, context
    )
    assert task["epic_key"] == epic["source_key"]

    note = await WorkItemNoteTool().execute(
        {"work_item": task["source_key"], "note": "started via chat agent"}, context
    )
    assert note["notes"] == 1

    result = await WorkItemContextTool().execute({"work_item": task["source_key"]}, context)
    assert result["work_item"]["source_key"] == task["source_key"]
    assert result["notes"][0]["note"] == "started via chat agent"


@pytest.mark.asyncio
async def test_tool_errors_are_returned_not_raised(db):
    context, _admin, _project = await _context(db)
    missing = await WorkItemContextTool().execute({"work_item": "NOPE-99"}, context)
    assert missing["status_code"] == 404
    bad_epic = await WorkItemCreateTool().execute(
        {"title": "x", "epic_key": "NOPE-1"}, context
    )
    assert bad_epic["status_code"] == 422
