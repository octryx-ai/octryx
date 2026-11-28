"""``POST /chat/api/send`` with a device target: the gate's explicit states, no server fallback, the
turn stored for the device, and server-only selections refused instead of ignored."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import DeviceJob, Message, Project, Session
from app.services.devices.hub import device_hub
from app.services.devices.jobs_channel import DeviceJobHandlers
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    device_with_grant,
    enable_device_runs,
    member_with_headers,
)

FOLDER = "/home/sample/src"


class Connected(RecordingConnection):
    seat_login = False


@pytest.fixture(autouse=True)
async def _device_runs_on(db):
    device_hub.clear()
    await enable_device_runs(db)
    yield
    device_hub.clear()


def _send(prompt="Run the tests", **target):
    return {"prompt": prompt, "execution_target": {"kind": "device", "folder": FOLDER, "profile": "governed",
                                                   **target}}


async def _counts(db):
    jobs = (await db.execute(select(func.count()).select_from(DeviceJob))).scalar_one()
    return jobs


@pytest.mark.asyncio
async def test_a_device_message_starts_a_turn_and_never_runs_on_the_server(client, db, auth_headers, auth_user):
    device, _ = await device_with_grant(db, auth_user)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    body = _send(device_id=device.id, folder=f"{FOLDER}/service")
    body["project_id"] = project.id

    offline = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert offline.status_code == 409
    assert offline.json()["detail"]["reason"] == "device_offline"
    assert await _counts(db) == 0

    connection = Connected(device.id)
    device_hub._connections[device.id] = connection
    response = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    session = await db.get(Session, job.session_id)
    assert session.user_id == auth_user.id and session.metadata_["execution_target"]["device_id"] == device.id
    assert session.run_status is None
    messages = (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert [(message.role, message.content) for message in messages] == [("user", "Run the tests")]
    await DeviceJobHandlers().tick(db, connection)
    assert connection.sent[0][0] == "job_offer" and connection.sent[0][1]["folder"] == f"{FOLDER}/service"

    busy = await client.post("/chat/api/send", json={**_send(device_id=device.id), "session_id": session.id},
                             headers=auth_headers)
    assert busy.json()["detail"]["reason"] == "device_job_busy"


@pytest.mark.asyncio
async def test_gate_refusals_are_explicit(client, db, auth_headers, auth_user):
    device, _ = await device_with_grant(db, auth_user)
    device_hub._connections[device.id] = Connected(device.id)
    session = await chat_session(db, auth_user)

    async def reason(**overrides):
        body = {**_send(device_id=device.id), "session_id": session.id}
        body["execution_target"].update(overrides.pop("target", {}))
        body.update(overrides)
        response = await client.post("/chat/api/send", json=body, headers=auth_headers)
        return response.status_code, response.json()["detail"]["reason"]

    assert await reason(workflow_key="incident-triage") == (409, "device_target_conflict")
    assert await reason(runtime_target_id="rt-1") == (409, "device_target_conflict")
    assert await reason(target={"folder": "/etc"}) == (403, "folder_not_allowlisted")
    assert await reason(target={"folder": f"{FOLDER}/../../etc"}) == (403, "device_target_invalid")
    # Seat is decided by the Workspace's seat decision first (unclassified Workspace here).
    assert await reason(target={"profile": "seat"}) == (403, "seat_classification_unresolved")
    device.paused = True
    await db.flush()
    assert await reason() == (403, "device_paused")
    device.paused, device.max_parallel_jobs = False, 1
    db.add(DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=(await chat_session(db,
               auth_user)).id, folder=FOLDER, profile="governed", status="running"))
    await db.flush()
    assert await reason() == (409, "device_busy")
    assert await _counts(db) == 1


@pytest.mark.asyncio
async def test_nobody_targets_another_users_device_or_thread(client, db, auth_headers, auth_user):
    member, member_headers = await member_with_headers(client, db, "other-member")
    device, _ = await device_with_grant(db, auth_user)
    device_hub._connections[device.id] = Connected(device.id)
    member_session = await chat_session(db, member)
    owner_session = await chat_session(db, auth_user)

    as_member = await client.post("/chat/api/send", json={**_send(device_id=device.id),
                                                          "session_id": member_session.id}, headers=member_headers)
    assert as_member.status_code == 403 and as_member.json()["detail"]["reason"] == "device_target_not_owner"
    # The admin owns the device but not the member's thread (a shared thread is never a device target).
    shared = await client.post("/chat/api/send", json={**_send(device_id=device.id), "session_id": member_session.id},
                               headers=auth_headers)
    assert shared.json()["detail"]["reason"] == "device_target_not_owner"
    own_thread_other_device = await client.post(
        "/chat/api/send", json={**_send(device_id="dev_missing"), "session_id": owner_session.id},
        headers=auth_headers)
    assert own_thread_other_device.json()["detail"]["reason"] == "device_target_not_owner"
    assert await _counts(db) == 0


async def _finished_device_thread(client, db, auth_headers, auth_user):
    from app.services.devices.job_events import apply_event

    device, _ = await device_with_grant(db, auth_user)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    connection = Connected(device.id)
    device_hub._connections[device.id] = connection
    body = {**_send("create test.txt with hello world", device_id=device.id), "project_id": project.id}
    response = await client.post("/chat/api/send", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                  "result_text": "Created test.txt."}, limits={})
    await db.flush()
    session = await db.get(Session, job.session_id)
    rows = (await db.execute(select(Message).where(Message.session_id == session.id)
                             .order_by(Message.created_at))).scalars().all()
    assert [(row.role, row.content) for row in rows] == [("user", "create test.txt with hello world"),
                                                          ("assistant", "Created test.txt.")]
    return device, connection, job, session, rows


@pytest.mark.asyncio
async def test_retry_on_a_device_thread_runs_on_the_device(client, db, auth_headers, auth_user):
    _device, connection, job, session, (user_message, answer) = await _finished_device_thread(
        client, db, auth_headers, auth_user)

    response = await client.post(f"/chat/api/sessions/{session.id}/messages/{answer.id}/rerun",
                                 json={"prompt": "create test.txt with hello world"}, headers=auth_headers)
    assert response.status_code == 200, response.text
    await db.refresh(session)
    await db.refresh(job)
    assert session.run_status is None
    assert "workflow_routing_policy_resolution" not in (session.metadata_ or {})
    rows = (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert [(row.id, row.role) for row in rows] == [(user_message.id, "user")]
    assert (job.status, job.turn_count, job.turn_prompt) == ("offered", 2, "create test.txt with hello world")
    await DeviceJobHandlers().tick(db, connection)
    assert [kind for kind, _ in connection.sent][-1] == "job_offer"


@pytest.mark.asyncio
async def test_a_refused_device_retry_keeps_the_history(client, db, auth_headers, auth_user):
    device, _connection, _job, session, (_user_message, answer) = await _finished_device_thread(
        client, db, auth_headers, auth_user)
    device_hub._connections.pop(device.id, None)

    response = await client.post(f"/chat/api/sessions/{session.id}/messages/{answer.id}/rerun",
                                 json={"prompt": "again"}, headers=auth_headers)
    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "device_offline"
    assert "offline" in response.json()["detail"]["message"]
    rows = (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert sorted(row.role for row in rows) == ["assistant", "user"]
