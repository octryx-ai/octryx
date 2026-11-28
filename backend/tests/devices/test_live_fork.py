"""Continue a *copy* of a running Claude Code session from the phone."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session
from app.services.devices.hub import device_hub
from app.services.devices.job_offer import offer_body
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.local_sessions import apply_report
from app.services.mobile.session import phone_may_use
from tests.devices.device_support import RecordingConnection, user_named
from tests.devices.test_local_sessions import SID, _mac, _report, _web

PEER = "uds:/tmp/cc-socks/4242.sock"


async def _listed(db, device_id, *, status="idle", session_id=SID):
    await DeviceJobHandlers().message(db, RecordingConnection(device_id), {"type": "live_sessions", "body": {
        "live": True, "sessions": [{"peer": PEER, "profile": "default", "pid": 4242, "session_id": session_id,
                                    "name": "octryx-pet", "cwd": "/Users/dev/projects", "status": status,
                                    "kind": "interactive", "updated_at": 1}]}})
    await db.commit()


@pytest.mark.asyncio
async def test_a_fork_is_a_new_mac_chat_resuming_a_copy_and_asking_before_writes(client, db, monkeypatch):
    user, device = await _mac(db, f"fork-{uuid.uuid4().hex[:6]}")
    device_id = device.id
    await apply_report(db, device, _report())
    await _listed(db, device_id)
    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)
    started = await client.post("/api/v1/mobile/live/fork", headers=_web(user),
                                json={"device_id": device_id, "peer": PEER, "message": "Mach du weiter"})
    assert started.status_code == 201, started.text
    data = started.json()
    assert data["title"] == "Fork of octryx-pet" and data["local_id"]
    thread = await db.get(Session, data["thread_id"])
    assert thread.metadata_["fork_of"]["name"] == "octryx-pet"
    job = await db.get(DeviceJob, data["job_id"])
    assert job.resume_claude_session_id == f"fork:{SID}" and job.turn_permission_mode == "default"
    body = offer_body(job, limits={})
    assert body["resume_session_id"] == SID and body["fork_session"] is True

    # once the copy has its own id, the next message continues the fork (never the original), still asking first
    job.status, job.claude_session_id = "idle", "f0f0f0f0-0000-4000-8000-000000000001"
    await db.commit()
    again = await client.post(f"/api/v1/mobile/local-sessions/{data['local_id']}/messages", headers=_web(user),
                              json={"message": "Und die Tests", "thread_id": thread.id})
    assert again.status_code == 201, again.text
    assert again.json()["thread_id"] == thread.id
    job = await db.get(DeviceJob, again.json()["job_id"])
    next_body = offer_body(job, limits={})
    assert next_body["resume_session_id"] == "f0f0f0f0-0000-4000-8000-000000000001"
    assert "fork_session" not in next_body and job.turn_permission_mode == "default"


@pytest.mark.asyncio
async def test_no_fork_of_a_working_unlisted_foreign_or_not_offered_session(client, db, monkeypatch):
    user, device = await _mac(db, f"fork-no-{uuid.uuid4().hex[:6]}")
    device_id = device.id
    await apply_report(db, device, _report())
    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)

    mine = _web(user)

    async def fork(headers=None, target=None, peer=PEER):
        return await client.post("/api/v1/mobile/live/fork", headers=headers or mine,
                                 json={"device_id": target or device_id, "peer": peer, "message": "go"})

    await _listed(db, device_id, status="busy")
    assert (await fork()).json()["reason"] == "session_busy"
    await _listed(db, device_id, session_id="1a2b3c4d-1111-2222-3333-444455556666")
    assert (await fork()).json()["reason"] == "takeover_not_allowed_on_device"
    await _listed(db, device_id)
    assert (await fork(peer="uds:/tmp/cc-socks/1.sock")).json()["reason"] == "session_not_running"
    intruder = await user_named(db, f"fork-intruder-{uuid.uuid4().hex[:6]}")
    await db.commit()
    assert (await fork(headers=_web(intruder))).json()["reason"] == "device_not_found"
    assert (await db.execute(select(DeviceJob).where(DeviceJob.device_id == device_id))).scalars().all() == []


@pytest.mark.asyncio
async def test_a_fork_thread_id_must_be_a_fork_of_that_session(client, db, monkeypatch):
    user, device = await _mac(db, f"fork-thread-{uuid.uuid4().hex[:6]}")
    device_id = device.id
    await apply_report(db, device, _report())
    await _listed(db, device_id)
    monkeypatch.setattr(device_hub, "reachable", lambda _device: True)
    local_id = (await client.get("/api/v1/mobile/local-sessions", headers=_web(user))).json()["items"][0]["id"]
    plain = await client.post(f"/api/v1/mobile/local-sessions/{local_id}/messages", headers=_web(user),
                              json={"message": "plain take-over"})
    assert plain.status_code == 201
    refused = await client.post(f"/api/v1/mobile/local-sessions/{local_id}/messages", headers=_web(user),
                                json={"message": "x", "thread_id": plain.json()["thread_id"]})
    assert refused.status_code == 404 and refused.json()["reason"] == "local_session_not_found"


def test_the_phone_may_fork():
    assert phone_may_use("POST", "/api/v1/mobile/live/fork") is True
    assert phone_may_use("GET", "/api/v1/mobile/live/fork") is False
