"""One run per device folder (``runtime_target.folder_lock``).

Runs started on one device folder would share one working tree, switch the branch under each other and push each
other's files in their WIP. A second run family's start or switch onto a
folder an active run holds is refused ``folder_busy``; another folder is fine.
"""

from __future__ import annotations

import pytest

from app.models import WorkItem
from app.services.workflow_runs.runtime_target.folder_lock import folder_key
from tests.devices.device_support import RecordingConnection, device_with_grant, enable_device_runs
from tests.phased_workflow_fixtures import admin_user
from tests.test_workflow_run_runtime_target import B_KEY, FOLDER, _hub  # noqa: F401 - clears the device hub
from tests.workflow_acceptance_support import _workspace, systems  # noqa: F401 - stubbed Jira and GitHub

OTHER = "/Users/dev/work/pay-2"


async def _setup(db, systems):  # noqa: F811
    from app.services.devices.hub import device_hub

    project, item = await _workspace(db, systems)
    await enable_device_runs(db, project.name)
    device, _ = await device_with_grant(db, await admin_user(db), name="Mac", folders=[FOLDER, OTHER],
                                        profiles=["governed"])
    device_hub._connections[device.id] = RecordingConnection(device.id)
    second = WorkItem(source_type="manual", source_instance="octryx", source_key=f"{item.source_key}-2",
                      source_project_key="PAY", title="Saved grinders vanish after a reload",
                      description="Steps: save a grinder, reload\nExpected: listed\nActual: gone",
                      project_id=project.id, work_state="intake")
    db.add(second)
    await db.commit()
    return item, second, device


def _target(device, folder: str) -> dict:
    return {"kind": "device", "device_id": device.id, "folder": folder, "profile": "governed"}


async def _start(client, auth_headers, item, target):
    return await client.post("/api/v1/workflow-runs", headers=auth_headers,
                             json={"workflow_key": B_KEY, "work_item_id": item.id, "runtime_target": target})


@pytest.mark.asyncio
async def test_a_second_run_on_a_busy_device_folder_is_refused_and_another_folder_is_fine(
        client, auth_headers, db, systems):  # noqa: F811
    item, second, device = await _setup(db, systems)
    first = await _start(client, auth_headers, item, _target(device, FOLDER))
    assert first.status_code == 200, first.text
    first_id = first.json()["run"]["id"]
    busy = await _start(client, auth_headers, second, _target(device, FOLDER + "/"))
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "folder_busy"
    assert first_id[:8] in busy.json()["detail"]["message"]
    other = await _start(client, auth_headers, second, _target(device, OTHER))
    assert other.status_code == 200, other.text
    # Switching onto the busy folder is refused the same way.
    switched = await client.post(f"/api/v1/workflow-runs/{other.json()['run']['id']}/actions", headers=auth_headers,
                                 json={"action": "change_runtime", "runtime_target": _target(device, FOLDER)})
    assert switched.status_code == 409 and switched.json()["detail"]["code"] == "folder_busy"


def test_only_a_device_target_with_a_folder_has_a_folder_key():
    assert folder_key({"kind": "device", "device_id": "d", "folder": "/a/b/"}) == ("d", "/a/b")
    assert folder_key({"kind": "server"}) is None and folder_key({"kind": "device", "device_id": "d"}) is None


async def _watching(db, run_id: str):
    """The run handed in its pull request and only watches it now (merge, CI)."""
    from app.models import WorkflowRun

    run = await db.get(WorkflowRun, run_id)
    run.status, run.waiting_kind = "waiting", "watching"
    run.pull_request = {"provider": "github", "id": "44", "url": "https://github.test/pr/44", "state": "open"}
    await db.commit()
    return run


@pytest.mark.asyncio
async def test_a_run_watching_its_pull_request_frees_the_folder_and_takes_it_back_only_when_free(
        client, auth_headers, db, systems):  # noqa: F811
    """A team member who handed in a PR is free for the next task (a new run can start in the folder of a finished
    one)."""
    from app.models import WorkflowRun
    from app.services.workflow_runs.runtime_target.device_wait import WAITABLE_REASONS
    from app.services.workflow_runs.runtime_target.folder_lock import folder_holder

    item, second, device = await _setup(db, systems)
    first = (await _start(client, auth_headers, item, _target(device, FOLDER))).json()["run"]["id"]
    a = await _watching(db, first)
    started = await _start(client, auth_headers, second, _target(device, FOLDER))
    assert started.status_code == 200, started.text  # B runs in the folder A only watched from
    b_id = started.json()["run"]["id"]
    # CI red: A needs the tree again, B holds it, so A's next turn waits folder_busy (resumed by the device's channel).
    a.status, a.waiting_kind = "running", None
    await db.commit()
    assert (await folder_holder(db, _target(device, FOLDER), run_id=a.id)).id == b_id
    assert "folder_busy" in WAITABLE_REASONS
    b = await db.get(WorkflowRun, b_id)
    b.status = "completed"
    await db.commit()
    assert await folder_holder(db, _target(device, FOLDER), run_id=a.id) is None  # free again: A takes it


@pytest.mark.asyncio
async def test_aborting_a_run_that_only_watches_its_open_pull_request_keeps_the_item_out_of_blocked(
        client, auth_headers, db, systems):  # noqa: F811
    from sqlalchemy import select

    from app.models.runtime.workflow_run import WorkflowRunEvent

    item, _second, device = await _setup(db, systems)
    item_id = item.id
    run_id = (await _start(client, auth_headers, item, _target(device, FOLDER))).json()["run"]["id"]
    await _watching(db, run_id)
    before = (await db.get(WorkItem, item_id)).work_state
    aborted = await client.post(f"/api/v1/workflow-runs/{run_id}/actions", headers=auth_headers,
                                json={"action": "abort", "reason": "octryx-e2e nightly: case done"})
    assert aborted.status_code == 200, aborted.text
    db.expire_all()
    assert (await db.get(WorkItem, item_id)).work_state == before != "blocked"
    kept = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run_id, WorkflowRunEvent.kind == "decision"))).scalars().all()
    assert any(dict(e.detail or {}).get("result") == "kept: pull request open" for e in kept)
