from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session, UserDevice, WorkflowRunDecision
from app.services.devices.engine_state import META_KEY, offer_session_state
from app.services.devices.hub import device_hub
from app.services.devices.registry import report_device_state
from app.services.devices.seat_engines import holds_seat
from app.services.workflow_runs import attention
from app.services.workflow_runs.actions import available_actions, perform_action
from app.services.workflow_runs.octryx.phase_sessions import SESSIONS_KEY
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.sweep import sweep_waiting_runs
from app.time_utils import utc_now
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phase_seat_models_support import seat_admitted  # noqa: F401 - fixture
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.workflow_run_octryx_continuation_support import DEFINITION, FOLDER, _confirm, _hub, _jobs  # noqa: F401

POOL_SEAT = {"kind": "device", "device_id": "pool", "profile": "seat"}
SNAPSHOT_SHA = "a" * 64


@pytest.fixture
def seat_allowed(monkeypatch, seat_admitted):  # noqa: F811
    from app.services.devices import device_models, device_policy
    from app.services.devices.dispatch_gate import DispatchDecision

    async def allowed(*_a, **_k):
        return DispatchDecision(True)

    async def any_model(*_a, model: str = "", **_k):
        return model, None

    monkeypatch.setattr(device_policy, "device_run_decision", allowed)
    monkeypatch.setattr(device_models, "admitted_device_model", any_model)


async def _seat_device(db, owner, *, online: bool = True, profiles=("governed", "seat"), seats=None) -> UserDevice:
    device, _ = await device_with_grant(db, owner, name="Laptop", profiles=list(profiles))
    if seats is not None:
        device.seat_engines = list(seats)
    if online:
        device_hub._connections[device.id] = RecordingConnection(device.id)
    return device


async def _paused_on_pool(db, *, device_online: bool | None = True, seats=None):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device = await _seat_device(db, admin, online=device_online, seats=seats) if device_online is not None else None
    thread = await new_chat_session(db, admin, project.id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, DEFINITION), project_id=project.id,
                          session=thread, runtime_target=POOL_SEAT)
    await _confirm(db, run, admin)
    return admin, device, thread, run


def _seat_target(device: UserDevice) -> dict:
    return {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "seat"}


@pytest.mark.asyncio
async def test_a_seat_phase_on_the_server_runners_pauses_seat_required_and_starts_no_turn(db):
    _admin, device, thread, run = await _paused_on_pool(db)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "seat_required", "work")
    pause = run.node_state["pause"]
    assert (pause["code"], pause["devices"], pause["cause"]) == ("seat_required", [device.name], "person")
    assert "Take it over on your device (Laptop)" in pause["message"]
    assert await _jobs(db, thread) == [], "no runner turn and no model call after the pause"


@pytest.mark.asyncio
async def test_without_a_seat_device_online_the_pause_says_so_by_name(db):
    _admin, _device, _thread, run = await _paused_on_pool(db, device_online=False)
    pause = run.node_state["pause"]
    assert pause["code"] == "no_seat_device_online" and pause["devices"] == []
    assert pause["message"].startswith("No device with a Claude Code seat online.")


@pytest.mark.asyncio
async def test_a_codex_run_counts_only_devices_that_reported_a_codex_seat(db, monkeypatch):
    from app.services.workflow_runs.review import choice

    async def codex(*_a, **_k):
        return "codex"

    monkeypatch.setattr(choice, "run_engine", codex)
    _admin, device, _thread, run = await _paused_on_pool(db, seats=["claude_code"])
    assert run.node_state["pause"]["code"] == "no_seat_device_online", "a Claude seat is no Codex seat"
    await report_device_state(db, device, {"seat_engines": ["codex"]})
    assert device.seat_engines == ["codex"] and holds_seat(device, "codex")


@pytest.mark.asyncio
async def test_a_report_keeps_what_it_does_not_name_and_drops_unknown_engines(db):
    admin = await admin_user(db)
    device = await _seat_device(db, admin)
    await report_device_state(db, device, {"seat_engines": ["codex", "codex", "other"], "engines": ["codex"]})
    await report_device_state(db, device, {"folders": [FOLDER]})
    assert (device.seat_engines, device.engines) == (["codex"], ["codex"])
    assert holds_seat(device, "codex") and not holds_seat(device, "claude_code")
    await report_device_state(db, device, {"seat_engines": [], "engines": []})
    assert (device.seat_engines, device.engines) == ([], []) and not holds_seat(device, "codex")


@pytest.mark.asyncio
async def test_the_requester_is_asked_to_take_over_on_their_device(db):
    admin, device, _thread, run = await _paused_on_pool(db)
    [item] = [item for item in await attention.inbox_items(db, admin.id) if item["id"] == run.id]
    assert item["title"] == f"Take over on your device: {run.title}"
    actions = await available_actions(db, run, access="write", user=admin)
    [runtime] = [action for action in actions if action["key"] == "change_runtime"]
    assert runtime["label"] == "Take over on your device"
    assert runtime["input"]["default"] == f"device:{device.id}:seat:{FOLDER}"
    assert not {action["key"] for action in actions} & {"continue", "change_plan"}


@pytest.mark.asyncio
async def test_taking_over_runs_the_phase_on_the_requesters_seat_in_the_same_thread(db, seat_allowed):
    admin, device, thread, run = await _paused_on_pool(db)
    await perform_action(db, run, user=admin, body={"action": "change_runtime", "runtime_target": _seat_target(device)})
    assert (run.status, run.pause_reason) == ("running", None) and "pause" not in run.node_state
    [job] = await _jobs(db, thread)
    assert (job.device_id, job.profile, job.session_id, job.status) == (device.id, "seat", thread.id, "offered")
    decision = (await db.execute(select(WorkflowRunDecision).where(WorkflowRunDecision.run_id == run.id))).scalars()
    assert [(d.subject, d.action, d.decided_by) for d in decision][-1] == ("seat_required", "change_runtime", admin.id)


@pytest.mark.asyncio
async def test_a_taken_over_turn_resumes_the_threads_snapshot_natively(db, seat_allowed):
    admin, device, thread, run = await _paused_on_pool(db)
    runner = await _seat_device(db, admin, profiles=("governed",))
    earlier = DeviceJob(device_id=runner.id, owner_user_id=admin.id, session_id=thread.id, folder="/work",
                        profile="governed", status="idle", claude_session_id="thread-1", engine="claude_code")
    db.add(earlier)
    await db.flush()
    run.context = {**run.context, SESSIONS_KEY: {"work": {
        "node_id": "work", "job_id": earlier.id, "turn_id": earlier.turn_id, "claude_session_id": "thread-1",
        "device_id": runner.id, "folder": "/work", "profile": "governed"}}}
    session = await db.get(Session, thread.id)
    session.metadata_ = {**dict(session.metadata_ or {}), META_KEY: {
        "engine": "claude_code", "engine_session_id": "thread-1", "sha256": SNAPSHOT_SHA}}
    await db.flush()
    await perform_action(db, run, user=admin, body={"action": "change_runtime", "runtime_target": _seat_target(device)})
    job = next(job for job in await _jobs(db, thread) if job.device_id == device.id)
    assert job.resume_claude_session_id == "thread-1"
    assert await offer_session_state(db, job) == {"sha256": SNAPSHOT_SHA, "engine": "claude_code",
                                                  "engine_session_id": "thread-1"}


@pytest.mark.asyncio
async def test_nobody_taking_over_leaves_the_run_paused_after_a_day(db):
    _admin, _device, thread, run = await _paused_on_pool(db, device_online=False)
    await sweep_waiting_runs(db, now=utc_now() + timedelta(hours=24))
    assert (run.status, run.pause_reason) == ("paused", "seat_required")
    assert run.node_state["pause"]["code"] == "no_seat_device_online"
    assert await _jobs(db, thread) == []
