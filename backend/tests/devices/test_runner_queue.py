"""Chat turns that wait for a free server runner: stored, offered first come first served, cancelled by Stop."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Message, Project, Session, UserDevice, UserProject
from app.services.devices.hub import device_hub
from app.services.devices.jobs import stop_active_jobs
from app.services.devices.jobs_channel import DeviceJobHandlers
from app.services.devices.runner_queue import claim_waiting
from tests.devices.device_support import chat_session, member_with_headers, user_named
from tests.devices.test_runner_pool import Connected, _enroll, _pool_send, _runners_on  # noqa: F401


async def _busy_runner(client, db, *, name="runner-a", parallel=1):
    runner = await db.get(UserDevice, (await _enroll(client, db, name)).json()["device"]["id"])
    runner.max_parallel_jobs = parallel
    device_hub._connections[runner.id] = Connected(runner.id)
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    other = await user_named(db, "runner-holder")
    holder = DeviceJob(device_id=runner.id, owner_user_id=other.id, session_id=(await chat_session(db, other)).id,
                       workspace_id=project.id, folder="/workspace/h0", profile="governed", status="running")
    db.add(holder)
    await db.flush()
    return runner, project, holder


async def _tick(db, runner):
    await DeviceJobHandlers().tick(db, device_hub._connections[runner.id])


@pytest.mark.asyncio
async def test_a_send_with_every_runner_busy_keeps_the_message_and_runs_when_a_runner_frees(
        client, db, auth_headers, auth_user):
    runner, project, holder = await _busy_runner(client, db)
    response = await _pool_send(client, auth_headers, project.id)
    assert response.status_code == 200, response.text
    job = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == auth_user.id))).scalar_one()
    assert (job.status, job.device_id, job.turn_prompt) == ("waiting_runner", None, "Fix the add function")
    assert (await db.execute(select(Message.content).where(Message.session_id == job.session_id,
                                                            Message.role == "user"))).scalars().all() == [
        "Fix the add function"]
    listed = await client.get("/api/v1/device-jobs", params={"session_id": job.session_id}, headers=auth_headers)
    assert [item["status"] for item in listed.json()["items"]] == ["waiting_runner"]

    holder.status = "idle"
    await db.flush()
    await _tick(db, runner)
    await db.refresh(job)
    assert (job.status, job.device_id, job.turn_state) == ("offered", runner.id, "sent")
    offer = [body for kind, body in device_hub._connections[runner.id].sent if kind == "job_offer"]
    assert [body["job_id"] for body in offer] == [job.id] and offer[0]["prompt"] == "Fix the add function"
    session = await db.get(Session, job.session_id)
    assert session.metadata_["execution_target"]["device_id"] == runner.id


@pytest.mark.asyncio
async def test_waiting_turns_go_first_come_first_served_one_person_per_runner(client, db, auth_headers, auth_user):
    runner, project, holder = await _busy_runner(client, db, parallel=4)
    holder.status = "idle"
    other_runner = await db.get(UserDevice, (await _enroll(client, db, "runner-b")).json()["device"]["id"])
    other_runner.max_parallel_jobs = 4
    device_hub._connections[other_runner.id] = Connected(other_runner.id)
    for device in (runner, other_runner):
        device.paused = True  # both away: every send waits
    await db.flush()
    second, second_headers = await member_with_headers(client, db, "second-sender")
    db.add(UserProject(user_id=second.id, project_id=project.id, role="member"))
    assert (await _pool_send(client, second_headers, project.id)).status_code == 200
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    first_waiting = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == second.id))).scalar_one()
    mine = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == auth_user.id))).scalar_one()

    runner.paused = False
    await db.flush()
    taken = await claim_waiting(db, runner)
    assert [job.id for job in taken] == [first_waiting.id]  # the oldest; the runner then serves only that person
    assert (await db.get(DeviceJob, mine.id)).status == "waiting_runner"
    assert await claim_waiting(db, runner) == []
    other_runner.paused = False
    await db.flush()
    assert [job.id for job in await claim_waiting(db, other_runner)] == [mine.id]
    assert (await db.get(DeviceJob, mine.id)).device_id == other_runner.id


@pytest.mark.asyncio
async def test_stop_cancels_the_wait_and_the_thread_can_send_again(client, db, auth_headers, auth_user):
    runner, project, holder = await _busy_runner(client, db)
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    job = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == auth_user.id))).scalar_one()
    again = await _pool_send(client, auth_headers, project.id, session_id=job.session_id)
    assert (again.status_code, again.json()["detail"]["reason"]) == (409, "device_job_busy")

    stopped = await client.post(f"/api/v1/device-jobs/{job.id}/stop", headers=auth_headers)
    assert (stopped.json()["status"], stopped.json()["status_reason"]) == ("closed", "cancelled_by_owner")
    holder.status = "idle"
    await db.flush()
    await _tick(db, runner)
    assert not [kind for kind, _ in device_hub._connections[runner.id].sent if kind == "job_offer"]
    resent = await _pool_send(client, auth_headers, project.id, session_id=job.session_id)
    assert resent.status_code == 200, resent.text
    newest = (await db.execute(select(DeviceJob).where(DeviceJob.session_id == job.session_id,
                                                       DeviceJob.id != job.id))).scalar_one()
    assert (newest.status, newest.device_id) == ("offered", runner.id)


@pytest.mark.asyncio
async def test_the_kill_switch_ends_waiting_turns_too(client, db, auth_headers, auth_user):
    _runner, project, _holder = await _busy_runner(client, db)
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    job = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == auth_user.id))).scalar_one()
    await stop_active_jobs(db, actor_id=auth_user.id, reason="kill_switch", workspace_id=project.id)
    await db.refresh(job)
    assert (job.status, job.status_reason) == ("closed", "kill_switch")


@pytest.mark.asyncio
async def test_a_turn_the_workspace_no_longer_allows_is_refused_when_a_runner_frees(
        client, db, auth_headers, auth_user):
    runner, project, holder = await _busy_runner(client, db)
    assert (await _pool_send(client, auth_headers, project.id)).status_code == 200
    job = (await db.execute(select(DeviceJob).where(DeviceJob.owner_user_id == auth_user.id))).scalar_one()
    project.config = {**(project.config or {}), "server_runners": "forbidden"}
    holder.status = "idle"
    await db.flush()
    await _tick(db, runner)
    await db.refresh(job)
    assert (job.status, job.status_reason) == ("rejected", "server_runners_forbidden")
    assert not [kind for kind, _ in device_hub._connections[runner.id].sent if kind == "job_offer"]


@pytest.mark.asyncio
async def test_an_api_turn_keeps_waiting_while_its_turn_waits_for_a_runner(client, db, auth_user):
    from app.services.devices.agent_runtime import run_pool_turn

    _runner, project, _holder = await _busy_runner(client, db)
    turn = await run_pool_turn(db, user_id=auth_user.id, prompt="Summarize", project_id=project.id, timeout=0.2)
    assert turn.state == "timeout"
    assert (await db.get(DeviceJob, turn.job_id)).status == "waiting_runner"


@pytest.mark.asyncio
async def test_an_idle_runner_takes_a_waiting_turn_from_a_private_workspace(client, db, auth_headers, auth_user):
    from app.services.data_access import as_viewer
    from app.services.devices.channel import DeviceChannelSession
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import FakeSocket, SharedSession

    runner, _project, holder = await _busy_runner(client, db)
    private = await ensure_private_workspace(db, auth_user)
    private.config = {**(private.config or {}), "agent_gateway_policy": {"device_runs": {"enabled": True}}}
    await db.commit()
    assert (await _pool_send(client, auth_headers, private.id)).status_code == 200
    holder.status = "idle"  # its person's turn ended; the job stays open on the runner
    await db.commit()

    channel = DeviceChannelSession(FakeSocket(), token="", session_factory=SharedSession(db))
    channel._runner = True
    for _round in range(2):  # the first tick takes the turn while it reads as nobody, the next one sends it
        with as_viewer(None):
            async with channel._for_turns(db, runner.id):
                await _tick(db, runner)
    offers = [body for kind, body in device_hub._connections[runner.id].sent if kind == "job_offer"]
    assert [body["workspace_id"] for body in offers] == [private.id]
    await db.refresh(holder)
    assert (holder.status, holder.status_reason) == ("closed", "runner_switched")


@pytest.mark.asyncio
async def test_a_runner_that_switches_person_closes_the_previous_persons_idle_job(client, db, auth_headers, auth_user):
    from app.services.data_access import as_viewer
    from app.services.devices.channel import DeviceChannelSession
    from app.services.project.private_workspace import ensure_private_workspace
    from tests.devices.device_support import FakeSocket, SharedSession

    runner, _project, holder = await _busy_runner(client, db)
    holder.status = "idle"
    private = await ensure_private_workspace(db, auth_user)
    private.config = {**(private.config or {}), "agent_gateway_policy": {"device_runs": {"enabled": True}}}
    await db.commit()
    assert (await _pool_send(client, auth_headers, private.id)).status_code == 200  # the runner is free: no wait
    await db.refresh(holder)
    assert (holder.status, holder.status_reason) == ("closed", "runner_switched")

    channel = DeviceChannelSession(FakeSocket(), token="", session_factory=SharedSession(db))
    channel._runner = True
    with as_viewer(None):
        async with channel._for_turns(db, runner.id):  # one person's open turns again: it reads as that person
            await _tick(db, runner)
    offers = [body for kind, body in device_hub._connections[runner.id].sent if kind == "job_offer"]
    assert [body["workspace_id"] for body in offers] == [private.id]
