"""The parallel work box never re-dispatches blindly: in-place dict changes, per-start threads and branch
reuse across worktrees each made every tick restart items; an abort leaves no item job running."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import DeviceJob, Session, WorkflowRunEvent
from app.services.devices.job_events import apply_event
from app.services.devices.job_state import ACTIVE_STATUSES
from app.services.workflow_runs.teamwork import (
    WORK_KEY,
    device_work_state,
    item_order,
    scheduler,
    work_git,
)
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.teamwork_device_support import (  # noqa: F401 - the device-run harness and its fixtures
    BRANCH,
    FOLDER,
    _gateway_session,
    _hub,
    _run,
    _set_item,
    admitted,
)

pytestmark = [pytest.mark.usefixtures("admitted"), pytest.mark.usefixtures("scripted_pool")]  # the Workspace admits the items' models

CLIENT_DIR = Path(__file__).resolve().parents[2] / "clients" / "octryx-claude"
PAST = "2000-01-01T00:00:00"


def _branched(run, keys=("api", "ui"), head="b" * 40):
    run.context = {**run.context, device_work_state.GIT_KEY: {"seq": 1, "branched": {
        key: {"folder": f"{FOLDER}/.octryx-items/{key}", "branch": f"{BRANCH}--{key}", "head": head} for key in keys}}}


async def _stored(db, run) -> dict:
    await db.flush()
    await db.refresh(run)
    return run.context[WORK_KEY]["items"]


async def _item_threads(db, thread) -> list[Session]:
    return list((await db.execute(select(Session).where(Session.parent_session_id == thread.id))).scalars())


async def _thread_jobs(db, session_id) -> list[DeviceJob]:
    return list((await db.execute(select(DeviceJob).where(DeviceJob.session_id == session_id)
                                  .order_by(DeviceJob.created_at))).scalars())


async def _reject(db, job_id: str, reason: str) -> None:
    job = await db.get(DeviceJob, job_id)
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": reason}, limits={})


@pytest.mark.asyncio
async def test_a_started_item_is_stored_running_and_the_next_tick_starts_nothing(db):
    admin, device, thread, run = await _run(db)
    _branched(run)
    await scheduler.advance(db, run)
    items = await _stored(db, run)
    assert {key: item["status"] for key, item in items.items()} == {"api": "running", "ui": "running"}
    assert all(item["session_id"] and item["job_id"] for item in items.values())

    for _ in range(3):  # the ticks that would re-dispatch the items
        await scheduler.advance(db, run)
    assert len(await _item_threads(db, thread)) == 2
    jobs = (await db.execute(select(func.count()).select_from(DeviceJob).where(
        DeviceJob.session_id.in_([item["session_id"] for item in items.values()])))).scalar_one()
    assert jobs == 2


@pytest.mark.asyncio
async def test_a_refused_item_job_is_retried_on_its_own_thread_with_backoff_then_fails(db):
    admin, device, thread, run = await _run(db)
    _branched(run)
    await scheduler.advance(db, run)
    session_id = (await _stored(db, run))["api"]["session_id"]

    for refusal in (1, 2):
        [*_, job] = await _thread_jobs(db, session_id)
        await _reject(db, job.id, "environment_not_ready")  # the device turned the job down before the agent ran
        api = (await _stored(db, run))["api"]
        assert (api["status"], api["start_refusals"], api["session_id"]) == ("pending", refusal, session_id)
        assert "environment_not_ready" in api["reason"] and api["retry_at"]
        assert run.node_state[item_order.WAKE_KEY] == api["retry_at"]  # the device channel's check starts it then
        for _ in range(3):  # ticks during the backoff start nothing
            await scheduler.advance(db, run)
        assert len(await _thread_jobs(db, session_id)) == refusal
        _set_item(run, "api", retry_at=PAST)
        await scheduler.advance(db, run)
        api = (await _stored(db, run))["api"]
        assert (api["status"], api["session_id"]) == ("running", session_id)  # the same thread, a new turn
        assert len(await _thread_jobs(db, session_id)) == refusal + 1

    [*_, job] = await _thread_jobs(db, session_id)
    await _reject(db, job.id, "environment_not_ready")
    api = (await _stored(db, run))["api"]
    assert api["status"] == "failed" and "refused 3 times" in api["reason"]
    assert "environment_not_ready" in api["reason"]
    assert "api" in "\n".join(item_order.findings(run.context[WORK_KEY]["items"]))  # what the coordinator re-plans
    assert len(await _item_threads(db, thread)) == 2  # one thread per item, whatever happened


@pytest.mark.asyncio
async def test_a_start_the_platform_refuses_counts_like_a_refused_job(db, monkeypatch):
    from app.services.devices import chat_turn

    admin, device, thread, run = await _run(db)
    _branched(run, keys=("api",))

    class Refused:
        reason = "folder_not_allowlisted"  # a reason waiting cannot fix (not busy, offline or paused)

    async def refused_start(*args, **kwargs):
        return Refused()

    monkeypatch.setattr(chat_turn, "start_device_turn", refused_start)
    await scheduler.advance(db, run)
    api = (await _stored(db, run))["api"]
    assert (api["status"], api["start_refusals"], api["attempts"]) == ("pending", 1, 0)
    assert api["session_id"] and "folder_not_allowlisted" in api["reason"]
    await scheduler.advance(db, run)  # still in its backoff: no new thread
    assert len(await _item_threads(db, thread)) == 1


@pytest.mark.asyncio
async def test_an_item_never_gets_a_second_open_thread_in_a_plan_version(db):
    admin, device, thread, run = await _run(db)
    _branched(run)
    await scheduler.advance(db, run)
    items = await _stored(db, run)
    # Whatever the stored split says (here: the item lost its session and job), the item's open thread is found
    # and its running turn is the item's.
    _set_item(run, "api", status="pending", session_id=None, job_id=None)
    await scheduler.advance(db, run)
    api = (await _stored(db, run))["api"]
    assert (api["status"], api["session_id"], api["job_id"]) == ("running", items["api"]["session_id"],
                                                                 items["api"]["job_id"])
    assert len(await _item_threads(db, thread)) == 2


@pytest.mark.asyncio
async def test_the_device_channels_check_starts_an_item_whose_backoff_ended(db):
    admin, device, thread, run = await _run(db)
    _branched(run, keys=("api",))
    await scheduler.advance(db, run)
    session_id = (await _stored(db, run))["api"]["session_id"]
    [job] = await _thread_jobs(db, session_id)
    await _reject(db, job.id, "registration_refused")
    assert (await _stored(db, run))["api"]["status"] == "pending"
    assert await scheduler.advance_due(db) == []  # not due yet

    _set_item(run, "api", retry_at=PAST)
    run.node_state = {**run.node_state, item_order.WAKE_KEY: PAST}
    assert await scheduler.advance_due(db) == [run.id]
    assert (await _stored(db, run))["api"]["status"] == "running"
    assert item_order.WAKE_KEY not in run.node_state


@pytest.mark.asyncio
async def test_abort_and_failure_stop_the_items_jobs_and_the_git_work(db):
    from app.services.workflow_runs.pause import abort_run
    from app.services.workflow_runs.run_end import fail_run

    admin, device, thread, run = await _run(db)
    _branched(run, keys=("api",))
    await scheduler.advance(db, run)  # "api" starts; "ui" has no worktree yet: its git work goes to the main thread
    git_job_id = run.context[device_work_state.GIT_KEY]["sent"]["job_id"]
    item_job_id = (await _stored(db, run))["api"]["job_id"]
    await abort_run(db, run, user=admin, reason="the work box looped")
    for job_id in (item_job_id, git_job_id):
        job = await db.get(DeviceJob, job_id)
        assert job.status not in ACTIVE_STATUSES or job.stop_state == "pending"

    admin, device, thread, run = await _run(db)
    _branched(run, keys=("api",))
    await scheduler.advance(db, run)
    item_job_id = (await _stored(db, run))["api"]["job_id"]
    await fail_run(db, run, "the coordinator gave up")
    job = await db.get(DeviceJob, item_job_id)
    assert job.status not in ACTIVE_STATUSES or job.stop_state == "pending"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], cwd=root, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.mark.asyncio
async def test_an_item_starts_on_the_device_path_end_to_end(db, tmp_path):
    if str(CLIENT_DIR) not in sys.path:
        sys.path.insert(0, str(CLIENT_DIR))
    from octryx_claude import work_git as launcher_git
    from octryx_claude import workspace_prep as launcher_prep

    from app.services.workflow_runs.octryx.attach import bind_device_session
    from app.services.workflow_runs.octryx.contract import run_contract
    from app.services.workflow_runs.workspace.gateway import report_preparation
    from app.services.workflow_runs.workspace.preparation import CONTEXT_KEY

    main = tmp_path / "kitchen-helper"
    main.mkdir()
    _git(main, "init", "-q", "-b", BRANCH)
    (main / "README.md").write_text("Kitchen helper\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "start")
    base = _git(main, "rev-parse", "HEAD")

    admin, device, thread, run = await _run(db)
    run.context = {**run.context, "base_sha": base, CONTEXT_KEY: {
        "state": "ready", "runtime": "device", "node_id": "prepare", "entry": 1,
        "spec": {"branch": BRANCH, "head": base, "repository": None, "environment": None}}}
    await scheduler.advance(db, run)  # no worktree yet: the git work goes to the main thread first
    assert (await _stored(db, run))["api"]["status"] == "pending"
    sent = run.context[device_work_state.GIT_KEY]["sent"]

    # The main thread's launcher runs the ops (its real code) and reports.
    results = []
    for op in sent["ops"]:
        result = launcher_git.branch(main, op["key"], op["branch"])
        results.append({**result, "folder": f"{FOLDER}/.octryx-items/{op['key']}"})  # the device's path for its folder
    assert await work_git.work_git_reported(db, run, {"seq": sent["seq"], "results": results}) == "recorded"
    api = (await _stored(db, run))["api"]
    assert api["status"] == "running" and api["path"] == f"{FOLDER}/.octryx-items/api"

    # The item job registers: its gateway session binds as the item's, next to nothing else of that item.
    gateway = await _gateway_session(db, admin, thread.project_id, "key-api")
    assert await bind_device_session(db, gateway_session=gateway, user=admin, workspace_id=thread.project_id,
                                     run_id=run.id, job_id=api["job_id"]) is not None
    contract = await run_contract(db, run, session=gateway)
    assert contract["preparation"]["branch"] == f"{BRANCH}--api" and contract["preparation"]["head"] == base

    # The launcher prepares the item's worktree from that contract: already on the item's branch, ready.
    worktree = main / ".octryx-items" / "api"
    report = launcher_prep.prepare(contract, worktree, runtime="device")
    assert report["branch"]["state"] == "already"
    answer = await report_preparation(db, session=gateway, payload=report)
    assert answer["state"] == "ready"
    assert run.context[CONTEXT_KEY]["state"] == "ready" and "reported_by" not in run.context[CONTEXT_KEY]

    # The run's own branch in that worktree is what git refuses: such a report refuses the
    # item's job and is noted on the item, never on the run's preparation, never a pause.
    refused = launcher_prep.prepare({**contract, "preparation": {**contract["preparation"], "branch": BRANCH}},
                                    worktree, runtime="device")
    assert refused["branch"]["state"] == "unavailable" and "already" in refused["branch"]["detail"]
    answer = await report_preparation(db, session=gateway, payload=refused)
    assert answer["state"] == "not_ready" and run.status == "running"
    assert run.context[CONTEXT_KEY]["state"] == "ready"
    await _reject(db, api["job_id"], "environment_not_ready")
    api = (await _stored(db, run))["api"]
    assert api["status"] == "pending" and api["start_refusals"] == 1 and "already" in api["reason"]
    events = (await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "workspace_preparation_reported"))).scalars().all()
    assert [event.detail.get("item") for event in events] == ["api", "api"]
