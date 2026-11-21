"""Device job recovery: a restarted service's turns and stalled turns end as failed with
the job back to idle; the owner's chat approval as the change confirmation on their own device; the device grant's
workflow scopes."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.models import AuditLog, DeviceJob, DeviceJobApproval, Session
from app.services.agent_gateway.tool_check import DECISION_DENY, ToolDecision
from app.services.devices import chat_confirmation
from app.services.devices.chat_confirmation import chat_confirmed_change
from app.services.devices.credential import device_grant_scopes
from app.services.devices.device_runs_keys import DeviceRunsPolicyError, normalize_device_runs
from app.services.devices.job_approvals import decide_approval
from app.services.devices.job_recovery import fail_stalled_turns
from app.services.devices.jobs import start_turn
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.time_utils import utc_now
from tests.devices.device_support import (
    RecordingConnection,
    chat_session,
    device_with_grant,
    gateway_login_token,
    user_named,
)

FOLDER = "/home/sample/src"
READ_ONLY = ToolDecision(DECISION_DENY, "denied", "capability_read_only", "capability-read-only", "read-only")


async def _running(db, user, device, session, handlers, connection):
    job = await start_turn(db, owner_user_id=user.id, device=device, session_id=session.id,
                           workspace_id=session.project_id, folder=FOLDER, profile="governed", prompt="Fix it")
    await handlers.tick(db, connection)
    await handlers.stream_event(db, connection, {"type": "job_accepted", "stream": job.id, "seq": 1,
                                                 "body": {"turn_id": job.turn_id}})
    return job


async def _age(db, job, minutes):
    await db.execute(update(DeviceJob).where(DeviceJob.id == job.id)
                     .values(updated_at=utc_now() - timedelta(minutes=minutes)))
    await db.refresh(job)


@pytest.mark.asyncio
async def test_a_restarted_service_reports_its_turn_failed_and_the_job_takes_the_next_message(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _running(db, user, device, session, handlers, connection)
    await handlers.stream_event(db, connection, {"type": "turn_finished", "stream": job.id, "seq": 2, "body": {
        "turn_id": job.turn_id, "status": "failed", "reason": "service_restarted"}})
    assert job.status == "idle" and job.status_reason == "service_restarted"
    follow_up = await start_turn(db, owner_user_id=user.id, device=device, session_id=session.id,
                                 workspace_id=session.project_id, folder=FOLDER, profile="governed", prompt="again")
    assert follow_up.id == job.id and follow_up.turn_state == "pending"


@pytest.mark.asyncio
async def test_a_turn_without_events_for_the_stale_time_fails_and_the_job_goes_idle(db):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    minutes = iter(range(0, 10**6, 60))  # every tick a minute later: the stall check runs on each
    handlers, connection = DeviceJobHandlers(clock=lambda: next(minutes)), RecordingConnection(device.id)
    job = await _running(db, user, device, session, handlers, connection)

    await _age(db, job, 5)
    assert await fail_stalled_turns(db, device_id=device.id) == []  # within the default 10 minutes
    await _age(db, job, 11)
    db.add(DeviceJobApproval(request_id="r1", job_id=job.id, owner_user_id=user.id, tool="Bash",
                             expires_at=utc_now() + timedelta(minutes=5)))
    await db.flush()
    assert await fail_stalled_turns(db, device_id=device.id) == []  # waiting for the owner is not stalled
    await db.execute(update(DeviceJobApproval).where(DeviceJobApproval.job_id == job.id).values(status="expired"))
    await _age(db, job, 11)

    connection.sent.clear()
    await handlers.tick(db, connection)
    await db.refresh(job)
    assert job.status == "idle" and job.turn_state == "failed" and job.status_reason == "turn_stalled"
    assert ("cancel", {"job_id": job.id, "turn_id": job.turn_id}) in connection.sent
    audit = (await db.execute(select(AuditLog).where(AuditLog.action == "device.job.turn_stalled"))).scalars().all()
    assert [row.resource_id for row in audit] == [job.id]


def test_stale_turn_minutes_and_the_chat_confirmation_flag_are_validated():
    assert normalize_device_runs({"stale_turn_minutes": 15, "chat_approvals_confirm_changes": False}, "p") == {
        "stale_turn_minutes": 15, "chat_approvals_confirm_changes": False}
    for bad in ({"stale_turn_minutes": 0}, {"chat_approvals_confirm_changes": "yes"}):
        with pytest.raises(DeviceRunsPolicyError):
            normalize_device_runs(bad, "p")


async def _launcher_session(db, user, project_id):
    session = Session(user_id=user.id, project_id=project_id, agent_type="external_agent", metadata_={})
    db.add(session)
    await db.flush()
    return session


def _hook(tool, cwd=FOLDER, **tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input, "cwd": cwd,
            "session_id": "cs-unknown"}


@pytest.mark.asyncio
async def test_on_the_owners_device_the_chat_approval_confirms_writes_and_is_audited(db, monkeypatch):
    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    chat = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await _running(db, user, device, chat, handlers, connection)
    launcher = await _launcher_session(db, user, chat.project_id)

    async def ask(hook):
        return await chat_confirmed_change(db, session=launcher, grant_id=device.grant_id, hook_input=hook,
                                           denial=READ_ONLY)

    answer = await ask(_hook("Bash", command="touch notes.txt"))
    assert answer["decision"] == "ask" and answer["reason"] == "device_chat_confirmation"
    assert (await ask(_hook("Bash", command="git push origin main")))["reason"] == "capability_deliver_required"
    assert (await ask(_hook("Edit", file_path="/etc/hosts")))["reason"] == "outside_device_job_folder"
    assert (await ask(_hook("Bash", cwd="/tmp", command="touch x"))) is None  # not the job's folder
    # A login that is not a device grant, or another denial, keeps the capability rule.
    await gateway_login_token(db, user)
    assert await chat_confirmed_change(db, session=launcher, grant_id=None, hook_input=_hook("Bash", command="x"),
                                       denial=READ_ONLY) is None
    destructive = ToolDecision(DECISION_DENY, "denied", "destructive_command", None, "")
    assert await chat_confirmed_change(db, session=launcher, grant_id=device.grant_id,
                                       hook_input=_hook("Bash", command="rm -rf /"), denial=destructive) is None

    # The owner allows the asked command in the chat: audited as a confirmed change with the owner as approver.
    await handlers.stream_event(db, connection, {"type": "approval_request", "stream": job.id, "seq": 2, "body": {
        "approval_id": "req-1", "tool": "Bash", "input_preview": "touch notes.txt"}})
    approval = (await db.execute(select(DeviceJobApproval).where(DeviceJobApproval.job_id == job.id))).scalar_one()
    await decide_approval(db, job_id=job.id, approval_id=approval.id, user_id=user.id, decision="allow_once")
    confirmed = (await db.execute(select(AuditLog).where(
        AuditLog.action == "device.job.change_confirmed"))).scalars().all()
    assert [(row.resource_id, row.details["tool"], row.details["approver_user_id"], row.details["via"])
            for row in confirmed] == [(job.id, "Bash", user.id, "allow_once")]

    # An edit inside the folder asks; after "Allow edits for this job" it is allowed, and audited.
    assert (await ask(_hook("Edit", file_path=f"{FOLDER}/a.py")))["decision"] == "ask"
    approval.status = "allowed_job_edits"
    approval.decided_at = utc_now()
    await db.flush()
    allowed = await ask(_hook("Edit", file_path=f"{FOLDER}/a.py"))
    assert allowed["decision"] == "allow"
    assert len((await db.execute(select(AuditLog).where(
        AuditLog.action == "device.job.change_confirmed"))).scalars().all()) == 2

    # The Workspace setting off: the change-workflow rule applies again.
    async def off(db, workspace_id, key):
        return False

    monkeypatch.setattr("app.services.devices.workspace_policy.workspace_device_setting", off)
    assert await ask(_hook("Bash", command="touch notes.txt")) is None
    assert chat_confirmation.SETTING_KEY == "chat_approvals_confirm_changes"


def test_the_device_grant_carries_the_workflow_scopes_of_the_login_only():
    login = ["model:invoke", "knowledge:read", "knowledge:write", "workflow:read", "workflow:execute", "work:manage"]
    assert device_grant_scopes(login) == ["device:connect", "knowledge:read", "model:invoke", "workflow:execute",
                                          "workflow:read"]
    assert "workflow:read" not in device_grant_scopes(["model:invoke"])


@pytest.mark.asyncio
async def test_a_turn_waiting_on_a_launcher_step_gets_longer_before_it_counts_as_stalled(db, monkeypatch):
    """The CI pipeline runs before the device accepts the turn and sends no event, so a pipeline longer than
    10 minutes must not end as stalled and pause its run: a launcher step gets 45 minutes."""
    from app.services.devices import job_recovery

    user = await user_named(db, "device-owner")
    device, _ = await device_with_grant(db, user)
    session = await chat_session(db, user)
    handlers, connection = DeviceJobHandlers(), RecordingConnection(device.id)
    job = await start_turn(db, owner_user_id=user.id, device=device, session_id=session.id,
                           workspace_id=session.project_id, folder=FOLDER, profile="governed", prompt="pipeline")
    await handlers.tick(db, connection)
    assert job.turn_state == "sent"

    async def at_pipeline(_db, _job):
        return True

    monkeypatch.setattr(job_recovery, "_launcher_step", at_pipeline)
    await _age(db, job, 20)
    assert await fail_stalled_turns(db, device_id=device.id) == []  # the pipeline still runs
    await _age(db, job, 50)
    assert [stalled.id for stalled in await fail_stalled_turns(db, device_id=device.id)] == [job.id]
