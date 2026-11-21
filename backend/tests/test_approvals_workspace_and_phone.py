"""Approvals name their Workspace, the chat note is neutral, and a person decides them on the phone.

Every approval carries its ``workspace_id``; the chat note names no admin chat; and deciding approvals on the go
needs the list of approvals a person may decide and approve/reject on the phone's surfaces.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Approval, Project
from app.services.auth import create_access_token
from app.services.mobile.session import phone_may_use
from app.services.tool_approval_gate import enforce_tool_approval
from app.tools.context import ToolContext
from tests.test_standing_tool_approvals import _session, _user

POLICY = {"approval_policy": {"require_for_tools": ["add_jira_comment"]}}


async def _workspace(db):
    project = Project(id=str(uuid.uuid4()), name=f"ap-{uuid.uuid4().hex[:8]}", config=dict(POLICY), is_active=True)
    db.add(project)
    await db.flush()
    return project, await _user(db, "owner", project)


def test_the_chat_decision_note_is_neutral():
    source = (Path(__file__).resolve().parents[1] / "app/web/routers/chat_approvals.py").read_text(encoding="utf-8")
    assert "from admin chat" not in source and '"Approved in chat"' in source


def test_the_phone_may_list_and_decide_approvals_but_not_always():
    assert phone_may_use("GET", "/api/v1/approvals/decidable")
    assert phone_may_use("POST", "/api/v1/approvals/abc/approve")
    assert phone_may_use("POST", "/api/v1/approvals/abc/reject")
    assert not phone_may_use("POST", "/api/v1/approvals/abc/always")


@pytest.mark.asyncio
async def test_the_decidable_list_carries_preview_and_offered_decisions(client, db):
    project, owner = await _workspace(db)
    session = await _session(db, project, owner)
    context = ToolContext(user_id=owner.id, project_ids=[project.id], roles=[], session_id=session.id,
                          project_config=dict(POLICY), db=db)
    blocked = await enforce_tool_approval("add_jira_comment", {"ticket_id": "CHEF-1", "comment": "x"}, context)
    await db.commit()

    listed = (await client.get("/api/v1/approvals/decidable",
                               headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})).json()
    [item] = [entry for entry in listed["items"] if entry["id"] == blocked["approval_id"]]
    assert item["offered_decisions"] == ["once", "deny"] and item["payload"]["toolName"] == "add_jira_comment"
    assert item["workspace_id"] == project.id
    stranger = await _user(db, "member", Project(id=str(uuid.uuid4()), name="x", config={}, is_active=True))
    others = (await client.get("/api/v1/approvals/decidable",
                               headers={"Authorization": f"Bearer {create_access_token(stranger.id)}"})).json()
    assert all(entry["id"] != blocked["approval_id"] for entry in others["items"])
    assert (await db.execute(select(Approval.status).where(Approval.id == blocked["approval_id"]))).scalar_one() \
        == "pending"
