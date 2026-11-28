"""Shared helpers for the test_workflow_run_octryx_continuation_* modules."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session
from app.services.devices.hub import device_hub
from app.services.workflow_runs.actions import perform_action
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased

FOLDER = "/home/sample/src"


DEFINITION = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "e1", "source_node_id": "go", "target_node_id": "work", "when": "confirmed"},
              {"id": "e2", "source_node_id": "go", "target_node_id": "blocked", "when": "changed"},
              {"id": "e3", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"},
              {"id": "e4", "source_node_id": "work", "target_node_id": "done"}],
}


async def _device_run(db, *, on_device: bool = True, definition: dict | None = None):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    device_hub._connections[device.id] = RecordingConnection(device.id)
    thread = await new_chat_session(db, admin, project.id)
    if on_device:
        thread.metadata_ = {**dict(thread.metadata_ or {}), "execution_target": {
            "kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed", "model": ""}}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition or DEFINITION), project_id=project.id,
                          session=thread)
    assert (run.status, run.current_node_id) == ("waiting", "go")
    return admin, device, thread, run


async def _confirm(db, run, admin):
    await perform_action(db, run, user=admin, body={"action": "confirm",
                                                    "payload_hash": run.node_state["waiting"]["payload_hash"]})


async def _jobs(db, thread: Session) -> list[DeviceJob]:
    return list((await db.execute(select(DeviceJob).where(DeviceJob.session_id == thread.id))).scalars())


TWO_PHASES = {
    **DEFINITION,
    "nodes": [*DEFINITION["nodes"][:3],
              {"id": "more", "type": "phase", "label": "More", "config": copy.deepcopy(PHASE)},
              *DEFINITION["nodes"][3:]],
    "edges": [*DEFINITION["edges"][:4], {"id": "e4", "source_node_id": "work", "target_node_id": "more"},
              {"id": "e5", "source_node_id": "more", "target_node_id": "done"}],
}


async def _reenter(db, run, node_id: str, *, runtime_step: bool = False):
    from app.services.workflow_runs.graph import graph_for_run
    from app.services.workflow_runs.octryx.continuation import phase_entered, runtime_step_entered

    node = (await graph_for_run(db, run)).nodes[node_id]
    run.current_node_id = node_id
    run.node_state = {"node_id": node_id, "iteration": 2, "entry": int(run.node_state["entry"]) + 1}
    await (runtime_step_entered if runtime_step else phase_entered)(db, run, node)


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()
