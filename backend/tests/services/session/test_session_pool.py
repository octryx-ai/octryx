from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session, SessionHandover, User, UserProject
from app.services.attention.handover_items import handover_entries
from app.services.devices.jobs import start_turn
from app.services.session import handover_pool, handovers
from app.services.session.handover_pool import can_run_now, pool_entries
from app.services.session.handovers import HandoverError, hand_over, take
from tests.devices.device_support import chat_session, keyed_device, member_with_headers
from tests.devices.test_agent_runtime_pool import _runner, pool  # noqa: F401
from tests.devices.test_runner_pool import _runners_on  # noqa: F401
from tests.phase_seat_models_support import seat_admitted  # noqa: F401 - fixture
from tests.policy_engine_support import make_user
from tests.test_workflow_run_seat_required import _jobs, _paused_on_pool, _seat_device, seat_allowed  # noqa: F401
from tests.workflow_run_octryx_continuation_support import FOLDER, _confirm, _device_run, _hub  # noqa: F401

SEAT = {"engine": "claude_code", "profile": "seat"}
GOVERNED = {"engine": "claude_code", "profile": "governed"}


async def _member(db, project_id: str, *, seat_device: bool = False) -> User:
    user = await db.get(User, await make_user(db, admin=False))
    db.add(UserProject(user_id=user.id, project_id=project_id, role="member"))
    await db.flush()
    if seat_device:
        await _seat_device(db, user)
    return user


async def _entry(db, run) -> SessionHandover:
    return (await db.execute(select(SessionHandover).where(SessionHandover.run_id == run.id))).scalar_one()


@pytest.mark.asyncio
async def test_a_seat_pause_offers_the_run_to_members_who_can_run_it_now(db):
    admin, _device, _thread, run = await _paused_on_pool(db, device_online=None)
    able = await _member(db, run.project_id, seat_device=True)
    unable = await _member(db, run.project_id)
    entry = await _entry(db, run)
    assert (entry.to_user_id, entry.source, entry.needs) == (None, "seat_required", SEAT)

    [listed] = await pool_entries(db, unable)
    assert listed["id"] == entry.id and listed["can_run_now"] is False and listed["state"] == "paused: seat_required"
    [offered] = [item for item in await handover_entries(db, able) if item["kind"] == "pool"]
    assert offered["id"] == run.id and offered["actions"][0]["request"]["path"].endswith(f"/{entry.id}/accept")
    assert not [item for item in await handover_entries(db, unable) if item["kind"] == "pool"]
    assert not [item for item in await handover_entries(db, admin) if item["kind"] == "pool"], "the holder's pause"


@pytest.mark.asyncio
@pytest.mark.usefixtures("seat_allowed")
async def test_a_member_takes_the_seat_run_and_it_continues_on_their_device_in_the_same_thread(db):
    _admin, _device, thread, run = await _paused_on_pool(db, device_online=None)
    taker = await _member(db, run.project_id, seat_device=True)
    taken = await take(db, (await _entry(db, run)).id, user=taker)
    assert taken["session_id"] == thread.id and taken["handover"]["status"] == "accepted"
    assert (run.requested_by, run.status, run.pause_reason) == (taker.id, "running", None)
    assert (await db.get(Session, thread.id)).user_id == taker.id
    [job] = await _jobs(db, thread)
    assert (job.owner_user_id, job.profile, job.session_id) == (taker.id, "seat", thread.id)
    assert await pool_entries(db, taker) == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("seat_allowed")
async def test_two_people_taking_the_same_entry_at_once_exactly_one_wins(db):
    _admin, _device, _thread, run = await _paused_on_pool(db, device_online=None)
    first = await _member(db, run.project_id, seat_device=True)
    second = await _member(db, run.project_id, seat_device=True)
    entry = await _entry(db, run)
    await handovers._claim(db, entry, first)
    entry.status = "pending"  # the second claim read the entry before the first one landed
    with pytest.raises(HandoverError) as lost:
        await handovers._claim(db, entry, second)
    assert lost.value.code == "handover_taken"
    assert (await _entry(db, run)).to_user_id == first.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("seat_allowed")
async def test_without_a_device_that_can_run_it_a_seat_entry_is_not_taken(db):
    _admin, _device, _thread, run = await _paused_on_pool(db, device_online=None)
    member = await _member(db, run.project_id)
    with pytest.raises(HandoverError) as refused:
        await take(db, (await _entry(db, run)).id, user=member)
    assert refused.value.code == "no_seat_device_online"


@pytest.mark.asyncio
async def test_a_pool_member_who_has_not_taken_the_session_cannot_read_its_session_file(client, db):
    owner = await db.get(User, await make_user(db, admin=False))
    mac, _private, _token = await keyed_device(db, owner, name="Mac")
    thread = await chat_session(db, owner)
    job = await start_turn(db, owner_user_id=owner.id, device=mac, session_id=thread.id,
                           workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="Build")
    await hand_over(db, user=owner, session_id=thread.id)
    member, member_headers = await member_with_headers(client, db, "pool-member")
    db.add(UserProject(user_id=member.id, project_id=thread.project_id, role="member"))
    _device, _key, member_token = await keyed_device(db, member, name="Member Mac")
    await db.commit()
    assert [entry["session_id"] for entry in await pool_entries(db, member)] == [thread.id]
    for headers in (member_headers, {"Authorization": f"Bearer {member_token}"}):
        read = await client.get(f"/api/v1/devices/jobs/{job.id}/session-state", headers=headers)
        assert read.status_code == 404


@pytest.mark.asyncio
async def test_a_seat_entry_is_never_offered_to_the_server_runners(db, monkeypatch):
    from app.services.devices import runner_pool

    async def one(*_a, **_k):
        return 1

    async def allowed(*_a, **_k):
        return True

    monkeypatch.setattr(runner_pool, "runners_online", one)
    monkeypatch.setattr(runner_pool, "pool_allowed", allowed)
    person = await db.get(User, await make_user(db, admin=False))
    assert await can_run_now(db, person, GOVERNED, "workspace") is True
    assert await can_run_now(db, person, SEAT, "workspace") is False


@pytest.mark.asyncio
async def test_only_the_holder_or_a_workspace_admin_puts_a_session_into_the_pool(db, monkeypatch):
    owner = await db.get(User, await make_user(db, admin=False))
    thread = await chat_session(db, owner)
    other = await _member(db, thread.project_id)
    with pytest.raises(HandoverError) as refused:
        await hand_over(db, user=other, session_id=thread.id)
    assert refused.value.code == "not_holder"

    async def workspace_admin(_db, user_id, _project_id):
        return user_id == other.id

    from app.services.agent_board import messages

    monkeypatch.setattr(messages, "is_workspace_admin", workspace_admin)
    entry = await hand_over(db, user=other, session_id=thread.id, reason="away this week")
    assert (entry.source, entry.from_user_id, entry.to_user_id, entry.needs) == ("admin", owner.id, None, GOVERNED)
    again = await hand_over(db, user=owner, session_id=thread.id)
    await db.refresh(entry)
    assert entry.status == "withdrawn" and again.status == "pending", "one open entry per session"
    assert handover_pool.STATUS_PENDING == again.status


@pytest.mark.asyncio
@pytest.mark.usefixtures("pool", "_runners_on")
async def test_a_gateway_session_taken_onto_a_server_runner_continues_there(client, db):
    runner, _project = await _runner(client, db)
    admin, _device, thread, run = await _device_run(db)
    taker = await _member(db, run.project_id)
    entry = await hand_over(db, user=admin, run_id=run.id, reason="on leave")
    assert entry.needs == GOVERNED and await can_run_now(db, taker, entry.needs, run.project_id)
    await take(db, entry.id, user=taker, runtime_target={"kind": "device", "device_id": "pool"})
    await _confirm(db, run, taker)
    [job] = [job for job in await _jobs(db, thread) if job.device_id == runner.id]
    assert (job.owner_user_id, job.profile, job.session_id) == (taker.id, "governed", thread.id)


@pytest.mark.asyncio
async def test_a_taken_session_leaves_the_holders_open_job_behind_and_a_running_turn_blocks_the_take(db):
    owner = await db.get(User, await make_user(db, admin=False))
    mac, _private, _token = await keyed_device(db, owner, name="Mac")
    thread = await chat_session(db, owner)
    job = await start_turn(db, owner_user_id=owner.id, device=mac, session_id=thread.id,
                           workspace_id=thread.project_id, folder=FOLDER, profile="governed", prompt="Build")
    entry = await hand_over(db, user=owner, session_id=thread.id)
    taker = await _member(db, thread.project_id)
    with pytest.raises(HandoverError) as busy:
        await take(db, entry.id, user=taker)
    assert busy.value.code == "runtime_busy" and entry.status == "pending"
    job.status = "idle"
    await take(db, entry.id, user=taker)
    assert (job.status, job.status_reason, job.owner_user_id) == ("closed", "handed_over", owner.id)
