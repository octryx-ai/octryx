"""An external write is never answered by "Always for this Workspace"; the card says what it offers.

A REST or connector write is approved per request or per write-plan
scope; a lasting exception is only the platform policy an admin sets explicitly. So the gate neither offers nor
honours a standing rule for one, every stored preview names its ``offered_decisions``, and the approval detail
(``GET /api/v1/approvals/{id}``) gives the page its payload, decisions, decider and run.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Approval, ChangePreview, Project
from app.services.auth import create_access_token
from app.services.standing_approvals.decision import decide_approval_always
from app.services.tool_approval_gate import enforce_tool_approval
from app.services.tool_approval_write_kinds import external_write
from app.tools.context import ToolContext
from tests.test_standing_tool_approvals import _session, _user

WRITE = "add_jira_comment"
POLICY = {"approval_policy": {"require_for_tools": [WRITE, "run_cli_command"]}}


async def _workspace(db):
    project = Project(id=str(uuid.uuid4()), name=f"ext-{uuid.uuid4().hex[:8]}", config=dict(POLICY), is_active=True)
    db.add(project)
    await db.flush()
    return project, await _user(db, "owner", project)


def _context(db, session, project) -> ToolContext:
    return ToolContext(user_id=session.user_id, project_ids=[project.id], roles=[], session_id=session.id,
                       project_config=dict(POLICY), db=db)


async def _preview(db, approval_id: str) -> dict:
    import json

    row = (await db.execute(select(ChangePreview).where(ChangePreview.approval_id == approval_id))).scalar_one()
    return json.loads(row.preview_json)


def test_connector_rest_and_deliver_writes_are_external_reads_and_local_changes_are_not():
    assert external_write(WRITE) is True
    assert external_write("http_request") is True
    assert external_write("get_jira_ticket") is False
    assert external_write("run_cli_command") is False


@pytest.mark.asyncio
async def test_an_external_write_offers_no_always_and_always_is_refused(db):
    project, owner = await _workspace(db)
    session = await _session(db, project, owner)

    blocked = await enforce_tool_approval(WRITE, {"ticket_id": "CHEF-1", "comment": "x"}, _context(db, session, project))
    preview = await _preview(db, blocked["approval_id"])
    assert preview["standing_rule"] is None and preview["offered_decisions"] == ["once", "deny"]
    with pytest.raises(HTTPException) as refused:
        await decide_approval_always(db, approval_id=blocked["approval_id"], decider_id=owner.id)
    assert refused.value.status_code == 409

    # A stored rule (e.g. set by hand) is not honoured for an external write.
    project.config = {**project.config, "standing_tool_approvals": {"rules": [{"tool_name": WRITE}]}}
    await db.flush()
    again = await enforce_tool_approval(WRITE, {"ticket_id": "CHEF-1", "comment": "y"}, _context(db, session, project))
    assert again is not None and again["approval_required"] is True

    # A local command keeps "Always".
    command = await enforce_tool_approval("run_cli_command", {"command": "git status"}, _context(db, session, project))
    assert (await _preview(db, command["approval_id"]))["offered_decisions"] == ["once", "always", "deny"]


@pytest.mark.asyncio
async def test_the_approval_detail_carries_payload_decisions_decider_and_names(client, db):
    project, owner = await _workspace(db)
    session = await _session(db, project, owner)
    blocked = await enforce_tool_approval(WRITE, {"ticket_id": "CHEF-1", "comment": "x"}, _context(db, session, project))
    await db.commit()

    detail = (await client.get(f"/api/v1/approvals/{blocked['approval_id']}",
                               headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})).json()
    assert detail["offered_decisions"] == ["once", "deny"]
    assert detail["payload"]["toolName"] == WRITE and detail["session_id"] == session.id
    assert detail["requested_by_name"] and detail["status"] == "pending" and detail["approved_by_name"] is None
    assert (await db.get(Approval, blocked["approval_id"])).status == "pending"
