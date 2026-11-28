"""An agent on a runner proposes a workflow with ``workflow_select``: the chat shows the composer's start card, and the
person's Allow starts the run (WP-C4a: no proposal model call per message)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Message, User, UserDevice
from app.models import Session as ChatSession
from app.services.devices import device_turn_results
from app.services.mcp_governed_knowledge import McpCaller
from app.services.mcp_workflow_tools import mcp_workflow_select
from tests.chat_phased_workflow_start_support import (  # noqa: F401
    IDEA,
    _approval,
    _record,
    _settle,
    _workspace,
    fakes,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.services.workflow_routing.test_chat_phased_workflow_start import _assert_started

pytestmark = [pytest.mark.workflow_proposals, pytest.mark.usefixtures("scripted_pool")]


async def _runner_turn_in_a_chat(db, project_id: str) -> tuple[User, ChatSession, DeviceJob]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    thread = ChatSession(user_id=admin.id, project_id=project_id, status="active", origin="chat",
                         metadata_={"title": "Hello Kitchen"})
    device = UserDevice(owner_user_id=admin.id, name="runner", name_key="runner", os="linux", public_key="k",
                        folders=["/workspace"], profiles=["governed"])
    db.add_all([thread, device])
    await db.flush()
    db.add(Message(session_id=thread.id, role="user", content=IDEA))
    job = DeviceJob(device_id=device.id, owner_user_id=admin.id, session_id=thread.id, workspace_id=project_id,
                    folder="/workspace/a", profile="governed", status="running", turn_count=1)
    db.add(job)
    await db.commit()
    return admin, thread, job


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_the_agents_workflow_select_shows_the_start_card_and_allow_starts_it(
        client, db, auth_headers, fakes, monkeypatch):  # noqa: F811
    state = fakes("spec-writing")
    project_id = await _workspace(db)
    admin, thread, job = await _runner_turn_in_a_chat(db, project_id)

    async def the_job(*_args):
        return job

    monkeypatch.setattr(device_turn_results, "caller_device_job", the_job)
    answer = await mcp_workflow_select(db, caller=McpCaller(user_id=admin.id, grant_id=None, scopes=("workflow:read",)),
                                       user=admin, workspace_id=project_id,
                                       arguments={"workflow_key": "spec-writing"})
    assert (answer["state"], answer["reason"]) == ("needs_confirmation", "start_card_in_chat")

    record = await _record(db, thread.id)
    assert (record["reason_code"], record["phased"]) == ("explicit_phased_selection", True)
    assert state["proposal"].calls == 0, "a selection makes no proposal call"
    approval = await _approval(db, thread.id)
    response = await client.post(f"/api/v1/approvals/{approval.id}/approve", json={}, headers=auth_headers)
    assert response.status_code == 200, response.text
    await _settle(thread.id)
    await _assert_started(db, state, thread.id, project_id, "spec-writing", "Epic", "Hello Kitchen",
                          source="jira", jira_line="Created Jira Epic CHEF-7 in CHEF. ")
