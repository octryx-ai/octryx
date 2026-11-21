"""The device list counts the jobs running on each device (the phone's device status): only running
jobs, only the owner's own, per device; the list itself stays the owner's."""

from __future__ import annotations

import pytest

from app.models import DeviceJob
from tests.devices.device_support import chat_session, keyed_device, member_with_headers


@pytest.mark.asyncio
async def test_each_device_shows_how_many_of_its_owners_jobs_run_now(client, db):
    owner, owner_headers = await member_with_headers(client, db, "mac-owner")
    _other, other_headers = await member_with_headers(client, db, "other-owner")
    busy, _key, _token = await keyed_device(db, owner, name="Busy Mac")
    await keyed_device(db, owner, name="Calm Mac")
    session = await chat_session(db, owner)
    for status in ("running", "running", "idle", "closed", "offered"):
        db.add(DeviceJob(device_id=busy.id, owner_user_id=owner.id, session_id=session.id, folder="/home/sample/src",
                         profile="governed", status=status))
    await db.flush()

    listed = {item["name"]: item for item in (await client.get("/api/v1/devices", headers=owner_headers)).json()["items"]}
    assert listed["Busy Mac"]["running_jobs"] == 2
    assert listed["Calm Mac"]["running_jobs"] == 0
    # Another person sees neither the devices nor their jobs.
    assert (await client.get("/api/v1/devices", headers=other_headers)).json()["items"] == []
