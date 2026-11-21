"""A Mac chat asks only for the events it does not have yet.

``known=job:seq,…`` makes those jobs answer only newer events (``partial``); every other job comes in full; a
malformed part is ignored (that job comes in full); another person's jobs stay invisible either way.
"""

from __future__ import annotations

import pytest

from app.services.devices.jobs_channel import DeviceJobHandlers
from tests.devices.device_support import RecordingConnection, chat_session, device_with_grant, member_with_headers
from tests.devices.test_device_jobs import _event, _turn


@pytest.mark.asyncio
async def test_known_jobs_answer_only_newer_events(db, client):
    owner, headers = await member_with_headers(client, db, "since-owner")
    device, _ = await device_with_grant(db, owner)
    session = await chat_session(db, owner)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, owner, device, session)
    await handlers.tick(db, connection)
    for seq in range(1, 6):
        await _event(db, handlers, connection, job, seq, "job_event", turn_id=job.turn_id, kind="text_delta",
                     text=f"part {seq}")
    await db.commit()
    url = f"/api/v1/device-jobs?session_id={session.id}"

    full = (await client.get(url, headers=headers)).json()["items"][0]
    assert [event["seq"] for event in full["events"]] == [1, 2, 3, 4, 5] and "partial" not in full

    delta = (await client.get(f"{url}&known={job.id}:3", headers=headers)).json()["items"][0]
    assert [event["seq"] for event in delta["events"]] == [4, 5]
    assert delta["partial"] is True and delta["since"] == 3 and delta["status"] == full["status"]

    nothing_new = (await client.get(f"{url}&known={job.id}:5", headers=headers)).json()["items"][0]
    assert nothing_new["events"] == [] and nothing_new["partial"] is True

    for bad in ("garbage", f"{job.id}:x", f"{job.id}:", ":3", f"{'j' * 50}:1"):
        item = (await client.get(f"{url}&known={bad}", headers=headers)).json()["items"][0]
        assert [event["seq"] for event in item["events"]] == [1, 2, 3, 4, 5] and "partial" not in item, bad


@pytest.mark.asyncio
async def test_known_never_shows_another_persons_jobs(db, client):
    owner, _ = await member_with_headers(client, db, "since-victim")
    _other, other_headers = await member_with_headers(client, db, "since-other")
    device, _ = await device_with_grant(db, owner)
    session = await chat_session(db, owner)
    job = await _turn(db, owner, device, session)
    await db.commit()
    seen = await client.get(f"/api/v1/device-jobs?session_id={session.id}&known={job.id}:0", headers=other_headers)
    assert seen.json()["items"] == []
