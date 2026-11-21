"""Where a workflow run executes is chosen at start.

If the device target were only set afterwards through the run's chat thread, ``workspace.prepare`` would run on the
Server, the device folder would never be prepared and the device's first turn would be refused (the run pausing at
Clarify). Here the target is part of the start:

- a device target: the run and its chat thread name the device, ``workspace.prepare`` offers the device a turn that
  carries the run id, the device's preparation report routes the step (the Server prepares nothing), and the Clarify
  turn runs on the same device;
- a Server target behaves;
- a foreign device, a folder outside the device's allowlist or a malformed target is refused and nothing is written;
- an offline device holds the run ``waiting_for_device`` and the run goes on when the device connects;
- the folder's remote is checked against the run's repository; switching the target is an explicit run action that
  prepares the new runtime, refused while a device turn runs; a chat message on the run's thread executes where the
  run executes or is refused.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import DeviceJob, Session, UserDevice, WorkflowRun
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.devices.jobs_channel import DeviceJobHandlers
from tests.device_job_session_parity_support import GATEWAY, REMOTE, _device, _headers, _register
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs, user_named
from tests.phased_workflow_fixtures import admin_user
from tests.server_build_lock import server_build_lock_lifted  # noqa: F401 - the switch test's server start
from tests.workflow_acceptance_support import (  # noqa: F401 - the stubbed Jira and GitHub fixture
    _settle,
    _workspace,
    systems,
)

B_KEY = "feature-delivery-tdd"
FOLDER = "/Users/dev/work/pay"
READY = {"state": "ready", "probes": [{"what": "test: python -m pytest", "ok": True}], "setup": []}


@pytest.fixture(autouse=True)
def _hub():
    device_hub.clear()
    yield
    device_hub.clear()


async def _device_workspace(db, systems, *, online: bool = True):  # noqa: F811
    project, item = await _workspace(db, systems)
    await enable_device_runs(db, project.name)
    device, _ = await device_with_grant(db, await admin_user(db), name="Mac", folders=[FOLDER],
                                        profiles=["governed", "seat"])
    if online:
        device_hub._connections[device.id] = RecordingConnection(device.id)
    await db.commit()
    return project, item, device


def _target(device, **extra) -> dict:
    return {"kind": "device", "device_id": device.id, "folder": FOLDER, "profile": "governed", **extra}


async def _start(client, auth_headers, item, target) -> tuple[int, dict]:
    started = await client.post("/api/v1/workflow-runs", headers=auth_headers,
                                json={"workflow_key": B_KEY, "work_item_id": item.id, "runtime_target": target})
    return started.status_code, started.json()


async def _jobs(db, session_id: str) -> list[DeviceJob]:
    return list((await db.execute(select(DeviceJob).where(DeviceJob.session_id == session_id)
                                  .order_by(DeviceJob.created_at))).scalars())


async def _device_session(client, db, project, run_id: str) -> dict:
    """The device's job session for the run (registered with the run id its job offer carried)."""
    token = await _device(db, await admin_user(db), [FOLDER])
    headers = _headers(token, project.id, run_id)
    assert (await _register(client, headers))["status"] == 200
    return headers


def _report(run: WorkflowRun, branch: dict, environment: dict | None = None, remote: str = REMOTE) -> dict:
    return {"node_id": "prepare", "entry": run.node_state["entry"], "root": FOLDER, "runtime": "device",
            "remote_url": remote, "branch": branch, **({"environment": environment} if environment else {})}


@pytest.mark.asyncio
async def test_a_device_target_prepares_on_the_device_before_the_clarify_turn_runs_there(
        client, auth_headers, db, systems):  # noqa: F811
    project, item, device = await _device_workspace(db, systems)
    status, body = await _start(client, auth_headers, item, _target(device))
    assert status == 200, body
    run_id, session_id = body["run"]["id"], body["session_id"]
    view = await _settle(client, auth_headers, run_id)
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    # The run waits at workspace.prepare for the device; the Server prepared nothing.
    assert (view["status"], view["current_node"]["id"]) == ("running", "prepare")
    assert view["runtime_target"]["kind"] == "device" and view["runtime_target"]["online"] is True
    prep = run.context["workspace_preparation"]
    assert (prep["state"], prep["runtime"]) == ("pending", "device") and "report" not in prep
    assert prep["spec"]["head"] and prep["spec"]["repository"] == {"provider": "github", "hosts": ["scm.stub.test"],
                                                                   "path": "acme/pay"}
    thread = await db.get(Session, session_id)
    assert thread.metadata_["execution_target"]["device_id"] == device.id
    [job] = await _jobs(db, session_id)
    assert (job.device_id, job.folder, job.status) == (device.id, FOLDER, "offered")
    # The device's job offer carries the run id: its session binds to the run at registration.
    connection = device_hub._connections[device.id]
    await DeviceJobHandlers().tick(db, connection)
    [offer] = [body for kind, body in connection.sent if kind == "job_offer"]
    assert offer["workflow_run_id"] == run_id and offer["job_id"] == job.id
    # The launcher prepares the folder before the agent starts and reports; the report routes the step.
    headers = await _device_session(client, db, project, run_id)
    answer = await client.post(f"{GATEWAY}/workspace-preparation", headers=headers, json=_report(
        run, {"state": "checked_out", "name": run.branch, "previous": "main"}, READY))
    assert answer.status_code == 200 and answer.json()["state"] == "ready", answer.text
    contract = answer.json()["workflow_run"]
    assert contract["phase"]["node_id"] == "clarify"  # the same device turn goes on with Clarify
    await db.refresh(run)
    assert run.current_node_id == "clarify" and run.context["actions"]["prepare"]["result"] == "succeeded"
    assert run.context["workspace_preparation"]["report"]["runtime"] == "device"
    # That turn ends without Clarify submitting anything (no questions, no result): the phase is not finished, so
    # the run pauses visibly instead of starting turn after turn; a resume
    # restarts Clarify on the device.
    job = await db.get(DeviceJob, job.id)
    # The pass already ended unfinished once: the second time (stall_after, default 2) pauses.
    from app.services.workflow_runs.octryx.same_pass import UNFINISHED_KEY

    run.context = {**dict(run.context or {}), UNFINISHED_KEY: {
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"), "times": 1}}
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    await db.refresh(run)
    pause = run.node_state.get("pause") or {}
    assert (run.status, pause.get("code")) == ("paused", "phase_not_finished"), (run.status, pause)
    assert run.current_node_id == "clarify" and job.status == "idle" and job.device_id == device.id


@pytest.mark.asyncio
async def test_a_server_target_is_refused_for_a_workflow_that_builds(client, auth_headers, db, systems):  # noqa: F811
    """B builds and tests the repository: never on the server; nothing is written."""
    _project, item, _device_row = await _device_workspace(db, systems)
    for target in ({"kind": "server"}, None):  # no target is the server
        status, body = await _start(client, auth_headers, item, target)
        assert (status, body["detail"]["code"]) == (409, "server_build_not_allowed"), body
        assert "not allowed on the Octryx server" in body["detail"]["message"]
    count = await db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.work_item_id == item.id))
    assert count == 0


@pytest.mark.asyncio
async def test_a_foreign_device_a_folder_outside_the_allowlist_or_a_malformed_target_is_refused(
        client, auth_headers, db, systems):  # noqa: F811
    _project, item, device = await _device_workspace(db, systems)
    other, _ = await device_with_grant(db, await user_named(db, "someone-else"), name="Theirs", folders=[FOLDER])
    await db.commit()
    refused = [
        (_target(other), 403, "runtime_device_not_owner"),
        (_target(device, folder="/etc"), 422, "runtime_folder_not_allowed"),
        (_target(device, profile="root"), 422, "runtime_profile_unavailable"),
        ({"kind": "laptop"}, 422, "runtime_target_invalid"),
        ({"kind": "device", "device_id": device.id}, 422, "runtime_target_invalid"),
    ]
    for target, code, reason in refused:
        status, body = await _start(client, auth_headers, item, target)
        assert (status, body["detail"]["code"]) == (code, reason), (target, body)
    count = await db.scalar(select(func.count()).select_from(WorkflowRun).where(WorkflowRun.work_item_id == item.id))
    assert count == 0  # nothing was written for a refused start


@pytest.mark.asyncio
async def test_an_offline_device_holds_the_run_waiting_for_device_until_it_connects(
        client, auth_headers, db, systems):  # noqa: F811
    _project, item, device = await _device_workspace(db, systems, online=False)
    status, body = await _start(client, auth_headers, item, _target(device))
    assert status == 200, body
    run_id, session_id = body["run"]["id"], body["session_id"]
    view = await _settle(client, auth_headers, run_id)
    assert (view["status"], view["waiting_kind"], view["current_node"]["id"]) == (
        "waiting", "waiting_for_device", "prepare")
    assert "Mac" in view["waiting"]["question"] and "is offline" in view["waiting"]["question"]
    assert view["runtime_target"]["online"] is False and await _jobs(db, session_id) == []
    assert "change_runtime" in {action["key"] for action in view["actions"]}
    # The device connects: its first tick resumes the run and offers the prepare turn with the run id.
    connection = RecordingConnection(device.id)
    device_hub._connections[device.id] = connection
    await DeviceJobHandlers().tick(db, connection)
    await db.commit()
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    assert (run.status, run.waiting_kind, run.current_node_id) == ("running", None, "prepare")
    [job] = await _jobs(db, session_id)
    assert job.status == "offered" and job.device_id == device.id
    await DeviceJobHandlers().tick(db, connection)
    assert [body["workflow_run_id"] for kind, body in connection.sent if kind == "job_offer"] == [run_id]


@pytest.mark.asyncio
async def test_a_folder_of_another_repository_never_counts_as_prepared(client, auth_headers, db, systems):  # noqa: F811
    project, item, device = await _device_workspace(db, systems)
    status, body = await _start(client, auth_headers, item, _target(device))
    run_id = body["run"]["id"]
    await _settle(client, auth_headers, run_id)
    run = await db.get(WorkflowRun, run_id)
    headers = await _device_session(client, db, project, run_id)
    answer = await client.post(f"{GATEWAY}/workspace-preparation", headers=headers, json=_report(
        run, {"state": "already", "name": run.branch}, READY, remote="https://scm.stub.test/acme/other.git"))
    assert answer.json()["state"] == "not_ready", answer.text
    await db.refresh(run)
    assert run.status == "paused" and "not the run's repository" in run.context["actions"]["prepare"]["reason"]


@pytest.mark.asyncio
async def test_switching_the_target_is_an_explicit_action_that_prepares_the_new_runtime(
        client, auth_headers, db, systems, server_build_lock_lifted):  # noqa: F811
    """The switch mechanics from a (pre-lock) server run; the lock itself: ``test_workflow_run_server_build_lock``."""
    from app.services.workflow_runs.runtime_target.send_guard import send_refusal

    _project, item, device = await _device_workspace(db, systems)
    status, body = await _start(client, auth_headers, item, {"kind": "server"})
    run_id, session_id = body["run"]["id"], body["session_id"]
    assert (await _settle(client, auth_headers, run_id))["current_node"]["id"] == "clarify"
    # A device message on the Server run's thread is refused, not a silent switch.
    refused = await send_refusal(db, session_id=session_id, device_target=_target(device))
    assert refused["reason"] == "runtime_target_mismatch" and "the Server" in refused["message"]
    switched = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                 json={"action": "change_runtime", "runtime_target": _target(device)})
    assert switched.status_code == 200, switched.text
    run = await db.get(WorkflowRun, run_id)
    await db.refresh(run)
    prep = run.context["workspace_preparation"]
    assert (prep["state"], prep["runtime"], prep["in_place"], prep["node_id"]) == ("pending", "device", True,
                                                                                    "clarify")
    assert run.context["runtime_target"]["device_id"] == device.id and run.current_node_id == "clarify"
    [job] = await _jobs(db, session_id)  # the device continues Clarify; its launcher prepares the folder first
    assert job.device_id == device.id and "phase 'Clarify'" in job.turn_prompt
    assert await send_refusal(db, session_id=session_id, device_target=_target(device)) is None
    assert (await send_refusal(db, session_id=session_id, device_target=None))["reason"] == "runtime_target_mismatch"
    busy = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                             json={"action": "change_runtime", "runtime_target": {"kind": "server"}})
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "runtime_busy"
    events = (await client.get(f"/api/v1/workflow-runs/{run_id}/events", headers=auth_headers)).json()["events"]
    assert any(event["kind"] == "runtime_target_changed" for event in events)


@pytest.mark.asyncio
async def test_the_start_dialog_offers_the_requesters_devices_and_defaults_to_their_last_choice(
        client, auth_headers, db, systems):  # noqa: F811
    project, item, device = await _device_workspace(db, systems)
    listed = (await client.get(f"/api/v1/workflow-runs/runtime-targets?project_id={project.id}",
                               headers=auth_headers)).json()
    keys = [option["key"] for option in listed["options"]]
    assert keys[:3] == ["auto", "server", "terminal"] and listed["default"] == "auto"
    assert f"device:{device.id}:governed:{FOLDER}" in keys and f"device:{device.id}:seat:{FOLDER}" in keys
    await _start(client, auth_headers, item, _target(device))
    listed = (await client.get(f"/api/v1/workflow-runs/runtime-targets?project_id={project.id}",
                               headers=auth_headers)).json()
    assert listed["default"] == f"device:{device.id}:governed:{FOLDER}"
    assert (await db.get(UserDevice, device.id)).owner_user_id == (await admin_user(db)).id


@pytest.mark.asyncio
async def test_switching_the_folder_keeps_the_runs_model_unless_the_switch_names_one(
        client, auth_headers, db, systems, monkeypatch):  # noqa: F811
    """A folder switch without a model must not write ``model: ""`` into the target, else the device falls back to
    Claude Code's default model instead of the chosen one.
    """
    from app.services.devices import device_models

    async def admitted(_db, *, model, **_kwargs):  # this test is about the switch, not the model admission
        return model, None

    monkeypatch.setattr(device_models, "admitted_device_model", admitted)
    other = "/Users/dev/work/pay-oe72"
    _project, item, device = await _device_workspace(db, systems, online=False)
    device.folders = [FOLDER, other]
    await db.commit()
    status, body = await _start(client, auth_headers, item, _target(device, model="claude-sonnet-5-5"))
    assert status == 200, body
    run_id = body["run"]["id"]
    await _settle(client, auth_headers, run_id)
    run = await db.get(WorkflowRun, run_id)
    chosen = run.context["runtime_target"]["model"]
    assert chosen == "claude-sonnet-5-5"
    switched = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers, json={
        "action": "change_runtime", "runtime_target": _target(device, folder=other)})
    assert switched.status_code == 200, switched.text
    await db.refresh(run)
    assert (run.context["runtime_target"]["folder"], run.context["runtime_target"]["model"]) == (other, chosen)
    thread = await db.get(Session, body["session_id"])
    await db.refresh(thread)
    assert thread.metadata_["execution_target"]["model"] == chosen
    explicit = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers, json={
        "action": "change_runtime", "runtime_target": _target(device, model="claude-haiku-5-5")})
    assert explicit.status_code == 200, explicit.text
    await db.refresh(run)
    assert run.context["runtime_target"]["model"] == "claude-haiku-5-5"
