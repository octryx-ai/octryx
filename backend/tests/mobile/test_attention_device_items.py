"""A session's answer over the live channel and the end of a Mac turn reach the attention queue, and so the
phone's push."""

from __future__ import annotations

import pytest

from app.models import DeviceJob, DeviceJobEvent, LiveMessage
from app.services.attention.service import attention
from app.services.mobile.push import group_of
from app.time_utils import utc_now
from tests.devices.device_support import chat_session, device_with_grant
from tests.mobile.mobile_live_support import cookie_client  # noqa: F401 - fixture
from tests.mobile.test_mobile_live import PEER, _reporting_device


@pytest.mark.asyncio
async def test_a_live_answer_needs_the_person_until_read(cookie_client, db, auth_user):  # noqa: F811
    device = await _reporting_device(db, auth_user)
    device_id = device.id
    db.add(LiveMessage(owner_user_id=auth_user.id, device_id=device_id, peer=PEER, direction="in", name="octryx-pet",
                       text="All green.", state="received", created_at=utc_now(), updated_at=utc_now()))
    await db.commit()
    [entry] = [item for item in (await attention(db, auth_user))["items"] if item["kind"] == "live"]
    assert entry["severity"] == "action" and group_of(entry) == "needs_you"
    assert entry["title"] == "octryx-pet answered you" and entry["text"] == "All green."

    read = await cookie_client.get("/api/v1/mobile/live/messages", params={"device_id": device_id, "peer": PEER})
    assert read.status_code == 200
    assert [item for item in (await attention(db, auth_user))["items"] if item["kind"] == "live"] == []

    db.add(LiveMessage(owner_user_id=auth_user.id, device_id=device_id, peer=PEER, direction="in", name="octryx-pet",
                       text="One more thing.", state="received", created_at=utc_now(), updated_at=utc_now()))
    await db.commit()
    assert [item["text"] for item in (await attention(db, auth_user))["items"] if item["kind"] == "live"] == [
        "One more thing."]


@pytest.mark.asyncio
async def test_a_finished_or_failed_mac_turn_is_reported_and_can_be_dismissed(client, db, auth_headers, auth_user):
    device, _ = await device_with_grant(db, auth_user)
    session = await chat_session(db, auth_user)
    job = DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=session.id, folder="/home/sample/src",
                    profile="governed", status="idle")
    db.add(job)
    await db.flush()
    for seq, body in enumerate([{"turn_id": "t1", "status": "success", "result_text": "Done: tests green."},
                                {"turn_id": "t2", "status": "error", "error": "claude_crashed"},
                                {"turn_id": "t3", "status": "stopped"}], start=1):
        db.add(DeviceJobEvent(job_id=job.id, seq=seq, type="turn_finished", body=body))
    await db.commit()
    turns = {item["key"]: item for item in (await attention(db, auth_user))["items"] if item["kind"] == "turn"}
    assert set(turns) == {f"turn:{job.id}:t1", f"turn:{job.id}:t2"}
    assert group_of(turns[f"turn:{job.id}:t2"]) == "problem" and group_of(turns[f"turn:{job.id}:t1"]) == "done"
    assert turns[f"turn:{job.id}:t1"]["session_id"] == session.id

    done = await client.post("/api/v1/attention/dismiss", headers=auth_headers, json={"key": f"turn:{job.id}:t1"})
    assert done.status_code in (200, 204), done.text
    keys = {item["key"] for item in (await attention(db, auth_user))["items"] if item["kind"] == "turn"}
    assert keys == {f"turn:{job.id}:t2"}


@pytest.mark.asyncio
async def test_a_turn_of_an_imported_sample_run_never_reads_as_the_persons_mac(db, auth_user):
    from app.models import WorkflowRun, WorkflowRunSession

    device, _ = await device_with_grant(db, auth_user)
    session = await chat_session(db, auth_user)
    run = WorkflowRun(workflow_kind="delivery", workflow_key="epic-delivery", title="Sample run: Story / epic delivery",
                      status="completed",
                      requested_by=auth_user.id, context={"sample_bundle": "ocx-2"})
    db.add(run)
    await db.flush()
    db.add(WorkflowRunSession(run_id=run.id, session_id=session.id, role="main", active=True))
    job = DeviceJob(device_id=device.id, owner_user_id=auth_user.id, session_id=session.id, folder="/home/demo/demo-ocx2",
                    profile="seat", status="idle")
    db.add(job)
    await db.flush()
    db.add(DeviceJobEvent(job_id=job.id, seq=1, type="turn_finished", body={"turn_id": "t1", "status": "success"}))
    await db.commit()

    [turn] = [item for item in (await attention(db, auth_user))["items"] if item["kind"] == "turn"]
    assert turn["sample"] is True
    assert turn["title"] == "Finished in the sample run (demo-ocx2)"
