"""Device jobs: sticky turns per thread, offers that carry only a prompt and its target, events stored
once, owner-only approvals with a timeout that denies, stop, and the offline grace."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceJob, DeviceJobApproval, DeviceJobEvent, Message
from app.services.devices.channel_protocol import RESULT_DUPLICATE, RESULT_STORED
from app.services.devices.job_approvals import decide_approval
from app.services.devices.job_state import DeviceJobError
from app.services.devices.jobs import mark_lost_jobs, request_stop, start_turn
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.time_utils import utc_now
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    device_with_grant,
    member_with_headers,
    user_named,
)

FOLDER = "/home/sample/src"


async def _turn(db, user, device, session, prompt="Run the tests", folder=FOLDER, profile="governed"):
    return await start_turn(db, owner_user_id=user.id, device=device, session_id=session.id,
                            workspace_id=session.project_id, folder=folder, profile=profile, prompt=prompt)


async def _event(db, handlers, connection, job, seq, message_type, **body):
    message = {"type": message_type, "stream": job.id, "seq": seq, "body": body}
    return await handlers.stream_event(db, connection, message)


@pytest.mark.asyncio
async def test_offer_carries_only_the_prompt_and_target_and_events_are_stored_once(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, user, device, session)

    await handlers.tick(db, connection)
    (kind, offer), = connection.sent
    assert kind == "job_offer"
    assert set(offer) == {"job_id", "turn_id", "prompt", "folder", "profile", "model", "workspace_id", "owner_user_id",
                          "chat_session_id", "resume_session_id", "policy_decision_id", "limits",
                          "workflow_run_id", "permission_mode", "effort", "lean", "engine", "web",
                          "browser_external"}  # web and public pages by default
    assert (offer["permission_mode"], offer["effort"]) == ("", "")  # the device's defaults
    assert offer["engine"] == "claude_code"  # no engine setting anywhere: Claude Code
    assert offer["workflow_run_id"] is None  # the thread follows no workflow run
    assert offer["prompt"] == "Run the tests" and offer["folder"] == FOLDER
    await handlers.tick(db, connection)
    assert len(connection.sent) == 1  # delivered once

    assert await _event(db, handlers, connection, job, 1, "job_accepted", turn_id=job.turn_id) == RESULT_STORED
    assert job.status == "running"
    assert await _event(db, handlers, connection, job, 1, "job_accepted", turn_id=job.turn_id) == RESULT_DUPLICATE
    assert await _event(db, handlers, connection, job, 3, "job_event", kind="text") == 2
    await _event(db, handlers, connection, job, 2, "job_event", kind="tool_result", output="x" * 9000)
    stored = (await db.execute(select(DeviceJobEvent).where(DeviceJobEvent.job_id == job.id))).scalars().all()
    assert [event.seq for event in stored] == [1, 2]
    assert len(stored[1].body["output"]) <= 4001  # tool results clipped to 4 KB

    other_device, _ = await device_with_grant(db, user, name="Other")
    assert await _event(db, handlers, RecordingConnection(other_device.id), job, 3, "job_event",
                        kind="text") == RESULT_DUPLICATE
    assert job.last_event_seq == 2  # another device's message about this job is never stored

    await _event(db, handlers, connection, job, 3, "turn_finished", turn_id=job.turn_id, status="success",
                 result_text="All tests pass.", claude_session_id="cs-1", cost_usd=0.12, model="claude-haiku-5-5")
    assert job.status == "idle" and job.claude_session_id == "cs-1"
    answer = (await db.execute(select(Message).where(Message.session_id == session.id))).scalars().all()
    assert [message.content for message in answer] == ["All tests pass."]
    # The answer names the model the device reported, not the profile ("device:governed").
    assert answer[0].model == "claude-haiku-5-5"
    assert answer[0].idempotency_key.startswith("device_job:")  # the chat reopens the thread on its device


@pytest.mark.asyncio
async def test_turns_are_sticky_per_thread_and_a_new_target_starts_a_new_job(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    job = await _turn(db, user, device, session)
    with pytest.raises(DeviceJobError) as busy:
        await _turn(db, user, device, session, prompt="again")
    assert busy.value.reason == "device_job_busy"
    job.status, job.claude_session_id = "idle", "cs-1"
    follow_up = await _turn(db, user, device, session, prompt="now fix it")
    assert follow_up.id == job.id and follow_up.turn_count == 2 and follow_up.turn_state == "pending"
    follow_up.status = "idle"
    moved = await _turn(db, user, device, session, prompt="other repo", folder="/home/sample/src/other")
    assert moved.id != job.id and moved.resume_claude_session_id is None
    moved.status, moved.claude_session_id = "rejected", None
    back = await _turn(db, user, device, session, folder="/home/sample/src/other")
    assert back.id != moved.id


@pytest.mark.asyncio
async def test_only_the_owner_decides_in_time_and_a_late_click_never_allows(db, client):
    owner, _owner_headers = await member_with_headers(client, db, "device-owner")
    _other, other_headers = await member_with_headers(client, db, "other-member")
    device, _ = await device_with_grant(db, owner)
    session = await chat_session(db, owner)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, owner, device, session)
    await _event(db, handlers, connection, job, 1, "job_accepted", turn_id=job.turn_id)
    await _event(db, handlers, connection, job, 2, "approval_request", approval_id="req-1", tool="Bash",
                 input_preview="pytest -q")
    await _event(db, handlers, connection, job, 3, "approval_request", approval_id="req-2", tool="Edit",
                 input_preview="parser.py")
    first, second = (await db.execute(select(DeviceJobApproval).order_by(DeviceJobApproval.created_at))).scalars()
    assert not first.can_allow_job_edits and second.can_allow_job_edits

    url = f"/api/v1/device-jobs/{job.id}/approvals/{first.id}"
    refused = await client.post(url, json={"decision": "allow_once"}, headers=other_headers)
    assert refused.status_code == 403 and refused.json()["reason"] == "device_approval_not_owner"
    with pytest.raises(DeviceJobError) as scope:
        await decide_approval(db, job_id=job.id, approval_id=first.id, user_id=owner.id, decision="allow_job_edits")
    assert scope.value.reason == "approval_job_edits_not_allowed"
    decided = await decide_approval(db, job_id=job.id, approval_id=first.id, user_id=owner.id, decision="allow_once")
    assert decided.status == "allowed"
    with pytest.raises(DeviceJobError) as again:
        await decide_approval(db, job_id=job.id, approval_id=first.id, user_id=owner.id, decision="deny")
    assert again.value.reason == "approval_already_decided"
    await handlers.tick(db, connection)
    assert ("approval_decision", {"job_id": job.id, "approval_id": "req-1", "decision": "allowed"}) in connection.sent

    second.expires_at = utc_now() - timedelta(seconds=1)
    await db.flush()
    with pytest.raises(DeviceJobError) as late:
        await decide_approval(db, job_id=job.id, approval_id=second.id, user_id=owner.id, decision="allow_once")
    assert late.value.reason == "approval_expired"
    await db.refresh(second)
    assert second.status == "expired"


@pytest.mark.asyncio
async def test_unanswered_approvals_expire_on_the_tick(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, user, device, session)
    await _event(db, handlers, connection, job, 1, "approval_request", approval_id="req-1", tool="Bash")
    approval = (await db.execute(select(DeviceJobApproval))).scalar_one()
    approval.expires_at = utc_now() - timedelta(seconds=1)
    await handlers.tick(db, connection)
    assert approval.status == "expired"


@pytest.mark.asyncio
async def test_stop_goes_to_the_device_and_an_undelivered_turn_just_ends(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, user, device, session)
    await request_stop(db, job, actor_id=user.id)
    assert job.status == "idle" and job.status_reason == "stopped_by_owner"
    await handlers.tick(db, connection)
    assert connection.sent == []

    job = await _turn(db, user, device, session, prompt="again")
    await handlers.tick(db, connection)
    await request_stop(db, job, actor_id=user.id)
    await handlers.tick(db, connection)
    assert connection.sent[-1] == ("cancel", {"job_id": job.id, "turn_id": job.turn_id})
    with pytest.raises(DeviceJobError):
        job.status = "idle"
        await request_stop(db, job, actor_id=user.id)


@pytest.mark.asyncio
async def test_offline_grace_then_device_lost_and_redelivery_after_reconnect(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _turn(db, user, device, session)
    await handlers.tick(db, connection)
    assert job.turn_state == "sent"
    streams = await handlers.welcome_streams(db, device)
    assert streams == {job.id: 0} and job.turn_state == "pending"  # sent again after a reconnect

    await handlers.disconnected(db, device.id)
    assert job.disconnected_at is not None
    assert await mark_lost_jobs(db) == []
    # A redeploy gap (observed up to ~2.5 min) is inside the grace; only a longer absence loses the job.
    job.disconnected_at = utc_now() - timedelta(minutes=3)
    assert await mark_lost_jobs(db) == []
    job.disconnected_at = utc_now() - timedelta(minutes=6)
    assert [lost.id for lost in await mark_lost_jobs(db)] == [job.id]
    assert job.status == "device_lost"


@pytest.mark.asyncio
async def test_thread_jobs_are_visible_to_the_owner_only(db, client):
    owner, owner_headers = await member_with_headers(client, db, "device-owner")
    _other, other_headers = await member_with_headers(client, db, "other-member")
    device, _ = await device_with_grant(db, owner)
    session = await chat_session(db, owner)
    job = await _turn(db, owner, device, session)
    mine = (await client.get(f"/api/v1/device-jobs?session_id={session.id}", headers=owner_headers)).json()
    assert [item["id"] for item in mine["items"]] == [job.id]
    theirs = (await client.get(f"/api/v1/device-jobs?session_id={session.id}", headers=other_headers)).json()
    assert theirs["items"] == []
    stop = await client.post(f"/api/v1/device-jobs/{job.id}/stop", headers=other_headers)
    assert stop.status_code == 404
    assert (await db.get(DeviceJob, job.id)).stop_state is None
