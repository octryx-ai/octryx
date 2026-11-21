"""Teamwork items on the run's device.

The scheduler is replaced by a recorder here: these tests pin what the device executor does with the platform's
real device jobs, sessions and bindings.

- each item runs on its own thread in ``<main>/.octryx-items/<key>`` with its own model, after the main thread's launcher
  branched it (the ``work_git`` contract); a busy device keeps the item pending;
- the item's gateway session registers by its job id and binds as ``octryx:<key>`` next to the main ``octryx`` one,
  with the item marker; its contract is its item's phase, its Stop reports to the item, its facts are ignored;
- the launcher's work-git report merges or conflicts items and sets the run's ``device_change``;
- a failed item turn reaches the scheduler; the main thread's ``work_git_done`` ends its job without a failure;
- the sequential fallback: one job slot, ``parallel: false``, a failed branch.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import DeviceJob, Session, UserDevice, WorkflowRunSession
from app.services.devices.job_events import apply_event
from app.services.devices.jobs import start_turn
from app.services.workflow_runs.records import new_chat_session
from app.services.workflow_runs.teamwork import (
    ITEM_METADATA_KEY,
    device_items,
    device_work_state,
    item_key_of,
    work_git,
)
from app.services.workflow_runs.teamwork.device_items import DeviceExecutor
from tests.teamwork_device_support import (  # noqa: F401
    BRANCH,
    FOLDER,
    ITEMS,
    _hub,
    _item_running,
    _jobs,
    _run,
    admitted,
    scheduler,
)


async def _branched(db, run, keys=("api",)):
    """The main thread's launcher reports the item worktrees (as octryx-claude ``work_git.branch``)."""
    state = run.context[device_work_state.GIT_KEY]
    report = {"seq": state["sent"]["seq"], "node_id": "work", "entry": 2, "results": [
        {"op": "branch", "key": key, "branch": f"{BRANCH}--{key}", "state": "branched",
         "folder": f"{FOLDER}/.octryx-items/{key}", "head": "b" * 40} for key in keys]}
    assert await work_git.work_git_reported(db, run, report) == "recorded"


@pytest.mark.asyncio
async def test_each_item_runs_on_its_own_thread_folder_and_model_after_the_main_thread_branched_it(db, scheduler,  # noqa: F811
                                                                                                  admitted):  # noqa: F811
    from app.services.workflow_runs.octryx.contract import run_contract

    admin, device, thread, run = await _run(db)
    executor = await device_items.executor_for(db, run)
    assert executor.name == "device" and executor.capacity(run) == 4  # the main thread takes no slot

    first = await executor.start(db, run, ITEMS["api"])
    assert first == {"status": "pending", "reason": "branching"}
    [git_job] = [job for job in await _jobs(db, thread.id) if job.status == "offered"]
    view = (await run_contract(db, run))["work_git"]
    assert view["ops"] == [{"op": "branch", "key": "api", "branch": f"{BRANCH}--api"}] and view["seq"] == 1
    assert git_job.id == run.context[device_work_state.GIT_KEY]["sent"]["job_id"]
    await executor.start(db, run, ITEMS["ui"])  # queued: the main thread's job is still busy with the first batch
    assert run.context[device_work_state.GIT_KEY]["ops"] == [{"op": "branch", "key": "ui", "branch": f"{BRANCH}--ui"}]

    await _branched(db, run)
    assert ("advance",) in scheduler.calls
    started = await executor.start(db, run, ITEMS["api"])
    assert started["status"] == "running" and started["path"] == f"{FOLDER}/.octryx-items/api"
    assert started["branch"] == f"{BRANCH}--api" and started["base"] == "b" * 40
    item_thread = await db.get(Session, started["session_id"])
    assert item_thread.origin == "sub_agent" and item_thread.parent_session_id == thread.id
    assert item_key_of(item_thread) == "api"
    assert item_thread.metadata_["execution_target"]["folder"] == f"{FOLDER}/.octryx-items/api"
    [job] = await _jobs(db, item_thread.id)
    assert (job.folder, job.turn_model, job.device_id) == (f"{FOLDER}/.octryx-items/api", "claude-haiku-5-5", device.id)
    assert "Search API" in job.turn_prompt and "workflow_run_status" in job.turn_prompt
    binding = (await db.execute(select(WorkflowRunSession).where(
        WorkflowRunSession.session_id == item_thread.id))).scalar_one()
    assert (binding.role, binding.active, binding.run_id) == ("item", True, run.id)


@pytest.mark.asyncio
async def test_a_model_the_workspace_refuses_falls_back_to_the_device_default(db, scheduler):  # noqa: F811
    from app.models import WorkflowRunEvent

    admin, device, thread, run = await _run(db)
    started, job = await _item_running(db, run)
    assert started["status"] == "running" and job.turn_model is None  # the device's default model
    events = (await db.execute(select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == run.id,
                                                              WorkflowRunEvent.kind == "run_turn_model_refused"))
              ).scalars().all()
    assert "claude-haiku-5-5" in [event.detail["model"] for event in events]


@pytest.mark.asyncio
async def test_a_busy_device_keeps_the_item_pending(db, scheduler):  # noqa: F811
    admin, device, thread, run = await _run(db, slots=2)
    run.context = {**run.context, device_work_state.GIT_KEY: {"seq": 1, "branched": {
        "api": {"folder": f"{FOLDER}/.octryx-items/api", "branch": f"{BRANCH}--api", "head": "b" * 40}}}}
    for _ in range(2):  # both slots taken by other turns
        other = await new_chat_session(db, admin, thread.project_id)
        await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                         session_id=other.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                         prompt="someone else's turn")
    started = await DeviceExecutor(slots=2).start(db, run, ITEMS["api"])
    # It keeps its thread: the next start reuses it (not a new thread per tick).
    assert (started["status"], started["reason"]) == ("pending", "device_busy") and started["session_id"]
    assert await DeviceExecutor(slots=2).start(db, run, ITEMS["api"]) == started


@pytest.mark.asyncio
async def test_the_work_git_report_merges_or_conflicts_and_sets_the_runs_change(db, scheduler):  # noqa: F811
    admin, device, thread, run = await _run(db)
    run.context = {**run.context, device_work_state.GIT_KEY: {"seq": 4, "branched": {"api": {}, "ui": {}}, "sent": {
        "seq": 4, "job_id": "j", "node_id": "work", "entry": 2,
        "ops": [{"op": "merge", "key": "api"}, {"op": "merge", "key": "ui"}]}}}
    stale = {"seq": 3, "results": [{"op": "merge", "key": "api", "state": "merged"}]}
    assert await work_git.work_git_reported(db, run, stale) == "stale" and scheduler.calls == []

    report = {"seq": 4, "node_id": "work", "entry": 2, "results": [
        {"op": "merge", "key": "api", "state": "merged", "head": "c" * 40},
        {"op": "merge", "key": "ui", "state": "conflict", "files": ["app.py"]}],
        "change": {"base": "a" * 40, "patch": "diff --git a/server/search.py b/server/search.py\n"}}
    assert await work_git.work_git_reported(db, run, report) == "recorded"
    assert ("merge_reported", "api", True, None, "c" * 40) in scheduler.calls
    assert ("merge_reported", "ui", False, ["app.py"], None) in scheduler.calls
    assert scheduler.calls[-1] == ("advance",)
    change = run.context["device_change"]
    assert change["patch"].startswith("diff --git a/server/search.py") and not change["base_unavailable"]
    state = run.context[device_work_state.GIT_KEY]
    # A conflicted item is branched again before its retry, with the story's work merged in.
    assert state["sent"] is None and not {"api", "ui"} & set(state["branched"]) and state["resync"] == ["ui"]


@pytest.mark.asyncio
async def test_a_failed_item_turn_reaches_the_scheduler_and_work_git_done_is_no_failure(db, scheduler):  # noqa: F811
    admin, device, thread, run = await _run(db)
    started, job = await _item_running(db, run)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "error",
                                                 "result_text": "API Error: 503 no available server"}, limits={})
    finished = [call for call in scheduler.calls if call[0] == "item_finished"]
    assert finished and finished[0][1:4] == ("api", "failed", True)  # transient: the scheduler resumes it once

    # The main thread's git work ends its job as done, never as a rejected or failed turn.
    run.context = {**run.context, device_work_state.GIT_KEY: {"seq": 1, "ops": [{"op": "branch", "key": "ui",
                                                                               "branch": f"{BRANCH}--ui"}]}}
    job_id = await work_git.flush(db, run)
    git_job = await db.get(DeviceJob, job_id)
    await work_git.work_git_reported(db, run, {"seq": 2, "results": [
        {"op": "branch", "key": "ui", "state": "branched", "folder": f"{FOLDER}/.octryx-items/ui"}]})
    await apply_event(db, git_job, "job_rejected", {"turn_id": git_job.turn_id, "reason": "work_git_done"},
                      limits={})
    assert git_job.status == "idle" and git_job.turn_state == "done" and git_job.status_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("setup", "reason"), [
    ({"slots": 1}, device_work_state.FALLBACK_ONE_SLOT),
    ({"parallel": False}, device_work_state.FALLBACK_NOT_PARALLEL),
])
async def test_the_sequential_fallback_matrix(db, scheduler, admitted, setup, reason):  # noqa: F811
    admin, device, thread, run = await _run(db, **setup)
    executor = await device_items.executor_for(db, run)
    assert (executor.name, executor.sequential, executor.capacity(run)) == ("sequential", reason, 1)
    started = await executor.start(db, run, ITEMS["api"])
    # In the main folder on the main thread, a fresh session with the item's own model; no worktree, no git work.
    assert started["status"] == "running" and started["session_id"] == thread.id and started["path"] == FOLDER
    job = await db.get(DeviceJob, started["job_id"])
    assert (job.folder, job.turn_model, job.session_id) == (FOLDER, "claude-haiku-5-5", thread.id)
    assert device_work_state.GIT_KEY not in run.context or not run.context[device_work_state.GIT_KEY].get("ops")
    await executor.merge(db, run, {**ITEMS["api"], "status": "done"})
    assert ("merge_reported", "api", True, None, None) in scheduler.calls  # built in place: nothing to merge


@pytest.mark.asyncio
async def test_a_failed_branch_falls_back_to_sequential(db, scheduler):  # noqa: F811
    admin, device, thread, run = await _run(db)
    executor = await device_items.executor_for(db, run)
    await executor.start(db, run, ITEMS["api"])
    state = run.context[device_work_state.GIT_KEY]
    await work_git.work_git_reported(db, run, {"seq": state["sent"]["seq"], "results": [
        {"op": "branch", "key": "api", "state": "failed", "detail": "fatal: not a git repository"}]})
    assert run.context[device_work_state.GIT_KEY]["fallback"] == device_work_state.FALLBACK_BRANCH_FAILED
    assert executor.capacity(run) == 1
    for job in await _jobs(db, thread.id):
        job.status = "idle"
    started = await executor.start(db, run, ITEMS["api"])
    assert started["session_id"] == thread.id and started["path"] == FOLDER


@pytest.mark.asyncio
async def test_a_new_device_folder_is_set_up_from_the_platforms_remote(tmp_path):
    """The preparation names the platform's remote without its credentials (a device folder for a repository the
    device cannot clone is initialised with it)."""
    import subprocess

    from app.services.workflow_runs.workspace.preparation import _server_remote

    copy_ = tmp_path / "copy"
    copy_.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=copy_, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://x-token-auth:secret@bitbucket.org/octryx/kitchen-helper.git"],
                   cwd=copy_, check=True)
    assert await _server_remote({"local_path": str(copy_)}) == "https://bitbucket.org/octryx/kitchen-helper.git"
    assert await _server_remote({}) == ""


def test_the_item_metadata_key():
    assert ITEM_METADATA_KEY == "workflow_run_item"
