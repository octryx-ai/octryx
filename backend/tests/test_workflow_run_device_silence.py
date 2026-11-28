"""A step waiting for its device pauses ``device_unreachable`` instead of waiting forever (when the device service
dies, a run must not stay ``running`` at ``pipeline`` indefinitely)."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models.runtime.workflow_run import WorkflowRunEvent
from app.services.devices.hub import device_hub
from app.services.workflow_runs.device_silence import sweep_device_steps
from app.services.workflow_runs.records import new_chat_session, record_event, start_run
from app.time_utils import utc_now
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture

pytestmark = pytest.mark.usefixtures("scripted_pool")

DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "pipeline", "type": "platform_action", "label": "CI", "config": {"action": "pipeline.run"}},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "e1", "source_node_id": "go", "target_node_id": "pipeline", "when": "confirmed"},
              {"id": "e2", "source_node_id": "pipeline", "target_node_id": "done", "when": "succeeded"},
              {"id": "e3", "source_node_id": "pipeline", "target_node_id": "blocked", "when": "failed"},
              {"id": "e4", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"}],
}


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _waiting_run(db, *, minutes: int, online: bool, definition: dict | None = None):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    device.last_seen_at = None
    if online:
        device_hub._connections[device.id] = RecordingConnection(device.id)
    thread = await new_chat_session(db, admin, project.id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or DEFINITION),
                          project_id=project.id, session=thread)
    run.status, run.waiting_kind, run.current_node_id = "running", None, "pipeline"
    run.context = {**dict(run.context or {}), "runtime_target": {
        "kind": "device", "device_id": device.id, "folder": "/src", "profile": "seat", "device_name": "mac"}}
    then = utc_now() - timedelta(minutes=minutes)
    await db.flush()
    for earlier in (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id))).scalars():
        earlier.created_at = then - timedelta(minutes=1)
    for kind, detail in (("node_entered", {"kind": "platform_action"}), ("waiting", {"action": "pipeline.run"})):
        record_event(db, run, kind, node_id="pipeline", detail=detail).created_at = then
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_a_silent_job_on_a_connected_device_pauses_after_its_timeout_and_offers_the_step_again(db):
    run = await _waiting_run(db, minutes=20, online=True)
    assert await sweep_device_steps(db, now=utc_now()) == 0 and run.status == "running"
    assert await sweep_device_steps(db, now=utc_now() + timedelta(minutes=11)) == 1
    await db.refresh(run)
    pause = run.node_state["pause"]
    assert (run.status, run.pause_reason) == ("paused", "device_unreachable")
    assert (pause["code"], pause["cause"], pause["cause_rule"]) == (
        "device_job_silent", "environment", "failure_codes.device_job_silent")
    assert pause["resume"] == {"kind": "restart", "node_id": "pipeline"} and "Next:" in pause["message"]


@pytest.mark.asyncio
async def test_an_offline_device_pauses_after_the_grace_time_and_the_node_config_wins(db):
    offline = await _waiting_run(db, minutes=6, online=False)
    assert await sweep_device_steps(db, now=utc_now()) == 1
    await db.refresh(offline)
    assert offline.node_state["pause"]["code"] == "device_offline"

    quick = copy.deepcopy(DEFINITION)
    quick["nodes"][2]["config"]["device_timeout_s"] = 120
    run = await _waiting_run(db, minutes=3, online=True, definition=quick)
    assert await sweep_device_steps(db, now=utc_now()) == 1
    await db.refresh(run)
    assert run.node_state["pause"]["code"] == "device_job_silent"


@pytest.mark.asyncio
async def test_a_step_that_reported_or_moved_on_is_not_paused(db):
    run = await _waiting_run(db, minutes=40, online=True)
    record_event(db, run, "node_entered", node_id="pipeline", detail={"kind": "platform_action"})
    await db.commit()
    assert await sweep_device_steps(db, now=utc_now()) == 0
    await db.refresh(run)
    assert run.status == "running"
