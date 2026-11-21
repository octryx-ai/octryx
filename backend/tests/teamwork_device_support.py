"""Shared helpers for the test_teamwork_device_* modules."""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session
from app.services.devices.hub import device_hub
from app.services.workflow_runs.records import new_chat_session, start_run
from app.services.workflow_runs.teamwork import WORK_KEY, device_work_state
from app.services.workflow_runs.teamwork.device_items import DeviceExecutor
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import PHASE, admin_user, publish_phased

FOLDER = "/home/sample/src"


BRANCH = "feature/CHEF-3-search"


def _definition(**work_config) -> dict:
    return {"execution_kind": "phased",
            "nodes": [{"id": "start", "type": "start"},
                      {"id": "work", "type": "phase", "label": "Work",
                       "config": {**copy.deepcopy(PHASE), **work_config}},
                      {"id": "done", "type": "outcome", "config": {"outcome": "done"}}],
            "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "work"},
                      {"id": "e1", "source_node_id": "work", "target_node_id": "done"}]}


ITEMS = {"api": {"id": "api", "title": "Search API", "role": "backend", "model": "claude-haiku-5-5",
                 "depends_on": [], "paths": ["server/**"], "instructions": "Build GET /search", "proofs": [],
                 "status": "pending", "iteration": 1, "attempts": 0},
         "ui": {"id": "ui", "title": "Search page", "role": "frontend", "model": None, "depends_on": [],
                "paths": ["web/**"], "instructions": "Build the page", "proofs": [], "status": "pending",
                "iteration": 1, "attempts": 0}}


class Scheduler:
    """The teamwork scheduler as a recorder."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def advance(self, db, run):
        self.calls.append(("advance",))

    async def merge_reported(self, db, run, *, key, merged, conflicts=None, merged_sha=None):
        self.calls.append(("merge_reported", key, merged, conflicts, merged_sha))

    async def item_finished(self, db, run, *, key, session_id, state, transient=False, reason=None):
        self.calls.append(("item_finished", key, state, transient, reason))


@pytest.fixture
def admitted(monkeypatch):
    """The Workspace admits the items' models for the profile."""
    from app.services.devices import chat_turn

    async def check(db, **kwargs):
        return None

    monkeypatch.setattr(chat_turn, "check_device_model", check)


@pytest.fixture
def scheduler(monkeypatch):
    from app.services.workflow_runs.teamwork import item_results
    from app.services.workflow_runs.teamwork import scheduler as module

    recorder = Scheduler()
    monkeypatch.setattr(module, "advance", recorder.advance)
    for name in ("merge_reported", "item_finished"):
        monkeypatch.setattr(item_results, name, getattr(recorder, name))
    return recorder


async def _run(db, *, slots=4, **work_config):
    """A device run at its parallel node (stood in by the phase ``work``) with a plan of two items."""
    project = await enable_device_runs(db)
    admin = await admin_user(db)
    device, _ = await device_with_grant(db, admin)
    device.client_version, device.max_parallel_jobs = "0.0.1a0+abc", slots
    device_hub._connections[device.id] = RecordingConnection(device.id)
    thread = await new_chat_session(db, admin, project.id)
    thread.metadata_ = {**dict(thread.metadata_ or {}), "execution_target": {
        "kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed", "model": ""}}
    run = await start_run(db, user=admin, workflow_key=await publish_phased(db, _definition(**work_config)),
                          project_id=project.id, session=thread)
    for job in (await db.execute(select(DeviceJob).where(DeviceJob.session_id == thread.id))).scalars():
        job.status = "idle"  # the phase continuation's turn of the stand-in node is not part of these tests
    run.status, run.current_node_id, run.node_state, run.branch = "running", "work", {"entry": 2}, BRANCH
    run.context = {**dict(run.context or {}), "base_sha": "a" * 40, "device_continuation": None,
                   WORK_KEY: {"node_id": "work", "plan_node": "plan", "executor": "device", "contract": "GET /search",
                              "items": copy.deepcopy(ITEMS)}}
    await db.flush()
    return admin, device, thread, run


def _set_item(run, key, **fields):
    work = dict(run.context[WORK_KEY])
    work["items"] = {**work["items"], key: {**work["items"][key], **fields}}
    run.context = {**run.context, WORK_KEY: work}


async def _jobs(db, session_id: str) -> list[DeviceJob]:
    return list((await db.execute(select(DeviceJob).where(DeviceJob.session_id == session_id))).scalars())


async def _gateway_session(db, admin, project_id: str, key: str) -> Session:
    from app.services.agent_gateway.contract import EXTERNAL_AGENT_TYPE, SESSION_KEY_METADATA

    session = Session(user_id=admin.id, project_id=project_id, agent_type=EXTERNAL_AGENT_TYPE, status="active",
                      origin="model_gateway", metadata_={SESSION_KEY_METADATA: key})
    db.add(session)
    await db.flush()
    return session


async def _item_running(db, run):
    executor = DeviceExecutor(slots=4)
    run.context = {**run.context, device_work_state.GIT_KEY: {"seq": 1, "branched": {
        "api": {"folder": f"{FOLDER}/.octryx-items/api", "branch": f"{BRANCH}--api", "head": "b" * 40}}}}
    started = await executor.start(db, run, ITEMS["api"])
    _set_item(run, "api", **started)
    [job] = await _jobs(db, started["session_id"])
    return started, job


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()
