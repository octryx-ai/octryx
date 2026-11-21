"""Shared helpers for the test_phase_sessions_models_* modules."""

# ruff: noqa: F811  (the shared ``seat_admitted`` fixture is imported, then requested by name)
from __future__ import annotations

import copy

from sqlalchemy import select

from app.models import ControlPlaneRuntimeTarget, UserDevice, WorkflowRunEvent
from app.services.workflow_runs.records import new_chat_session, start_run
from tests.devices.device_support import enable_device_runs
from tests.phase_seat_models_support import OPUS  # noqa: F401 - fixture
from tests.phased_workflow_fixtures import admin_user, publish_phased
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401 - autouse fixture: a clean device hub
    _confirm,
    _device_run,
)


def _with_phase(definition: dict, node_id: str, **config) -> dict:
    definition = copy.deepcopy(definition)
    node = next(node for node in definition["nodes"] if node["id"] == node_id)
    node["config"] = {**node["config"], **config}
    return definition


async def _events(db, run, kind: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind))).scalars())


# --- the phase's model on the seat ---------------------------------------------------------------------------------

async def _seat_run(db, definition: dict):
    admin, device, thread, run = await _device_run(db, definition=definition)
    (await db.get(UserDevice, device.id)).profiles = ["governed", "seat"]
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "profile": "seat", "model": OPUS}}
    return admin, thread, run


SONNET = "claude-sonnet-5-5"


# --- the phase's model on the server --------------------------------------------------------------------------------

async def _target(db, model_id: str, *, active: bool = True, priority: int = 50) -> ControlPlaneRuntimeTarget:
    template = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    target = ControlPlaneRuntimeTarget(config_id=template.config_id, provider_id=template.provider_id,
                                       model_id=model_id, priority=priority, is_active=active)
    db.add(target)
    await db.flush()
    return target


async def _server_run(db, definition: dict):
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    thread = await new_chat_session(db, admin, project.id)
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, definition), project_id=project.id,
                          session=thread, runtime_target={"kind": "server"})
    await _confirm(db, run, admin)
    return thread, run
