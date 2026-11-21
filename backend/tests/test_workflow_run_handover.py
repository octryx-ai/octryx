"""Handing a workflow run over to a Workspace member, and the admin emergency stop.

Contract: only the requester (or an admin) asks, with a reason, for an active member; the receiver alone accepts or
declines and sees the request in the attention queue; accepting moves the run to the receiver with a new thread and
an ``auto`` target, every step an event and an audit row. An admin's emergency stop needs a reason, aborts the run
and is audited; nobody else may use it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, User, UserProject, WorkflowRunEvent
from app.services.devices.hub import device_hub
from tests.policy_engine_support import bearer, make_user
from tests.workflow_run_octryx_continuation_support import _device_run


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _member(db, project_id: str) -> User:
    user = await db.get(User, await make_user(db, admin=False))
    db.add(UserProject(user_id=user.id, project_id=project_id, role="member"))
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_a_run_is_handed_over_only_with_the_receivers_consent(client, db):
    admin, _device, thread, run = await _device_run(db)
    receiver = await _member(db, run.project_id)
    stranger = await db.get(User, await make_user(db, admin=False))
    await db.commit()
    path = f"/api/v1/workflow-runs/{run.id}"

    refused = await client.post(f"{path}/handover-requests", headers=bearer(admin.id),
                                json={"to_user_id": stranger.id, "reason": "vacation"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "handover_receiver_not_member"
    asked = await client.post(f"{path}/handover-requests", headers=bearer(admin.id),
                              json={"to_user_id": receiver.id, "reason": "vacation"})
    assert asked.status_code == 200

    queue = (await client.get("/api/v1/attention", headers=bearer(receiver.id))).json()
    [entry] = [item for item in queue["items"] if item["kind"] == "handover"]
    assert entry["id"] == run.id and entry["text"] == "vacation"
    accept = next(action for action in entry["actions"] if action["key"] == "accept")["request"]
    assert (await client.post(accept["path"], headers=bearer(stranger.id))).status_code == 403

    taken = await client.post(accept["path"], json=accept["body"], headers=bearer(receiver.id))
    assert taken.status_code == 200
    await db.refresh(run)
    assert run.requested_by == receiver.id and run.context["handover"]["state"] == "accepted"
    # The receiver also becomes the responsible person.
    assert (run.responsible_user_id, run.responsible_source) == (receiver.id, "accepted")
    assert run.context["handover"]["decided_at"].endswith("+00:00") and run.context["handover"]["at"].endswith("+00:00")
    assert run.context["runtime_target"]["resolved_from"] == "auto"
    assert taken.json()["session_id"] != thread.id
    kinds = [event.kind for event in (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id))).scalars()]
    assert "handover_requested" in kinds and "handover_accepted" in kinds
    audits = {row.action for row in (await db.execute(select(AuditLog).where(
        AuditLog.resource_id == run.id))).scalars()}
    assert {"workflow_run.handover.requested", "workflow_run.handover.accepted"} <= audits


@pytest.mark.asyncio
async def test_a_declined_handover_keeps_the_run_with_its_requester(client, db):
    admin, _device, _thread, run = await _device_run(db)
    receiver = await _member(db, run.project_id)
    await db.commit()
    path = f"/api/v1/workflow-runs/{run.id}"
    await client.post(f"{path}/handover-requests", headers=bearer(admin.id),
                      json={"to_user_id": receiver.id, "reason": "too much"})
    declined = await client.post(f"{path}/handover/decline", json={"reason": "busy"}, headers=bearer(receiver.id))
    assert declined.status_code == 200
    await db.refresh(run)
    assert run.requested_by == admin.id and run.context["handover"]["state"] == "declined"
    assert run.context["handover"]["decided_at"].endswith("+00:00")
    assert (await client.post(f"{path}/handover/accept", headers=bearer(receiver.id))).status_code == 409


@pytest.mark.asyncio
async def test_the_emergency_stop_is_an_audited_admin_action(client, db):
    admin, _device, _thread, run = await _device_run(db)
    member = await _member(db, run.project_id)
    await db.commit()
    path = f"/api/v1/workflow-runs/{run.id}/emergency-stop"
    assert (await client.post(path, json={"reason": "leak"}, headers=bearer(member.id))).status_code == 403
    assert (await client.post(path, json={"reason": " "}, headers=bearer(admin.id))).status_code == 422
    assert (await client.post(path, json={"reason": "leaking secrets"}, headers=bearer(admin.id))).status_code == 200
    await db.refresh(run)
    assert run.status == "stopped"
    [audit] = (await db.execute(select(AuditLog).where(AuditLog.action == "workflow_run.emergency_stop",
                                                       AuditLog.resource_id == run.id))).scalars()
    assert audit.details["reason"] == "leaking secrets" and audit.user_id == admin.id


@pytest.mark.asyncio
async def test_members_of_a_workspace_are_listed_for_its_members_only(client, db):
    admin, _device, _thread, run = await _device_run(db)
    member = await _member(db, run.project_id)
    stranger = await db.get(User, await make_user(db, admin=False))
    await db.commit()
    listed = (await client.get(f"/api/v1/workspaces/{run.project_id}/members", headers=bearer(member.id))).json()
    assert member.id in {person["id"] for person in listed["members"]}
    assert set(listed["members"][0]) == {"id", "display_name"}
    assert (await client.get(f"/api/v1/workspaces/{run.project_id}/members",
                             headers=bearer(stranger.id))).status_code == 404
    assert admin.id
