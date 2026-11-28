"""A run's device turn the launcher refused never leaves the run ``running`` with nothing driving it."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm.attributes import set_committed_value

from app.models import DeviceJob, WorkflowRun, WorkflowRunEvent
from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from app.services.workflow_runs.octryx.turn_failures import is_transient_rejection
from app.services.workflow_runs.runtime_target.device_wait import REASON_PLATFORM_RETRY, resume_for_device
from app.time_utils import utc_now
from tests.phased_workflow_fixtures import PHASE
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import _confirm, _device_run, _hub, _jobs  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")

UNREACHABLE = "workspace_preparation_platform_unreachable"

WITH_PREPARE = {
    "execution_kind": "phased",
    "nodes": [{"id": "start", "type": "start"},
              {"id": "go", "type": "user_confirmation", "label": "Go on?", "config": {"subject": "advance"}},
              {"id": "prepare", "type": "platform_action", "label": "Prepare",
               "config": {"action": "workspace.prepare"}},
              {"id": "work", "type": "phase", "label": "Work", "config": copy.deepcopy(PHASE)},
              {"id": "done", "type": "outcome", "config": {"outcome": "done"}},
              {"id": "blocked", "type": "outcome", "config": {"outcome": "blocked"}}],
    "edges": [{"id": "e0", "source_node_id": "start", "target_node_id": "go"},
              {"id": "e1", "source_node_id": "go", "target_node_id": "prepare", "when": "confirmed"},
              {"id": "e2", "source_node_id": "go", "target_node_id": "blocked", "when": "changed"},
              {"id": "e3", "source_node_id": "go", "target_node_id": "blocked", "when": "stopped"},
              {"id": "e4", "source_node_id": "prepare", "target_node_id": "work", "when": "succeeded"},
              {"id": "e5", "source_node_id": "prepare", "target_node_id": "blocked", "when": "failed"},
              {"id": "e6", "source_node_id": "work", "target_node_id": "done"}],
}


async def _at_work(db):
    admin, device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    return admin, device, thread, run, job


async def _reject(db, job, reason: str) -> None:
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": reason}, limits={})


async def _after_backoff(db, run, device) -> list[str]:
    waiting = run.node_state["waiting"]
    run.node_state = {**run.node_state, "waiting": {**waiting, "retry_after": (
        utc_now() - timedelta(seconds=1)).isoformat()}}
    return await resume_for_device(db, device.id)


async def _events(db, run, kind: str) -> list[WorkflowRunEvent]:
    return list((await db.execute(select(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == kind))).scalars())


def test_only_a_platform_the_device_could_not_reach_counts_as_a_temporary_refusal():
    for reason in (UNREACHABLE, "registration_platform_unreachable", "client_policy_platform_connect_failed",
                   "workspace_preparation_refused", "registration_refused", "hook_key_timeout", "device_updating",
                   "device_restarted", "pipeline_report_unreachable"):
        assert is_transient_rejection(reason), reason
    for reason in ("folder_not_allowlisted_on_device", "profile_unavailable_on_device", "claude_not_installed",
                   "codex_seat_not_logged_in", "registration_refused_run_read_only", "workspace_dirty",
                   "environment_not_ready", "device_busy", "model_not_offered", ""):
        assert not is_transient_rejection(reason), reason


@pytest.mark.asyncio
async def test_a_turn_refused_for_an_unreachable_platform_is_offered_once_more_then_the_run_pauses(db):
    admin, device, thread, run, job = await _at_work(db)
    await _reject(db, job, UNREACHABLE)
    waiting = run.node_state["waiting"]
    assert (run.status, run.waiting_kind, waiting["reason"]) == ("waiting", "waiting_for_device", REASON_PLATFORM_RETRY)
    assert "could not reach the platform" in waiting["question"]
    assert run.context[CONTEXT_KEY]["state"] == "pending"
    [retry] = await _events(db, run, "device_turn_retry")
    assert retry.detail["failure"] == UNREACHABLE and retry.detail["rejected"] is True
    assert await resume_for_device(db, device.id) == []

    assert await _after_backoff(db, run, device) == [run.id]
    jobs = await _jobs(db, thread)
    [again] = [item for item in jobs if item.id != job.id]
    assert (run.status, again.status, again.folder) == ("running", "offered", job.folder)
    assert run.context[CONTEXT_KEY]["job_id"] == again.id
    assert "phase 'Work'" in again.turn_prompt and "temporary error" not in again.turn_prompt

    await _reject(db, again, UNREACHABLE)
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "turn_failed", "work")
    pause = run.node_state["pause"]
    assert pause["code"] == f"device_turn_{UNREACHABLE}" and pause["resume"] == {"kind": "restart", "node_id": "work"}
    assert "could not start the turn" in pause["message"] and "reachable from the device" in pause["message"]
    assert len(await _jobs(db, thread)) == 2 and CONTEXT_KEY not in run.context


@pytest.mark.asyncio
async def test_a_turn_refused_for_a_lasting_reason_pauses_the_run_at_once(db):
    _admin, _device, thread, run, job = await _at_work(db)
    await _reject(db, job, "profile_unavailable_on_device")
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "turn_failed", "work")
    pause = run.node_state["pause"]
    assert pause["code"] == "device_turn_profile_unavailable_on_device"
    assert "could not start the turn" in pause["message"] and "reachable" not in pause["message"]
    assert await _events(db, run, "device_turn_retry") == [] and len(await _jobs(db, thread)) == 1


def _ended_unfinished_once(run) -> None:
    from app.services.workflow_runs.octryx.same_pass import UNFINISHED_KEY

    run.context = {**dict(run.context or {}), UNFINISHED_KEY: {
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"), "times": 1}}


@pytest.mark.asyncio
async def test_a_normal_turn_is_not_retried_and_ends_as_before(db):
    _admin, _device, thread, run, job = await _at_work(db)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    _ended_unfinished_once(run)
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    assert (run.status, run.pause_reason, run.node_state["pause"]["code"]) == (
        "paused", "phase_not_finished", "phase_not_finished")
    assert job.status == "idle" and len(await _jobs(db, thread)) == 1
    assert await _events(db, run, "device_turn_retry") == []


@pytest.mark.asyncio
async def test_a_refusal_judges_the_run_as_it_is_once_claimed_not_as_it_was_read(db):
    from app.services.workflow_runs.engine import restart_at
    from app.services.workflow_runs.records import _CLAIMS
    from app.services.workflow_runs.workspace.preparation import record_report

    admin, device, thread, run = await _device_run(db, definition=WITH_PREPARE)
    run.branch = "octryx/story-1"
    await restart_at(db, run, "prepare", actor_id=None)
    [job] = await _jobs(db, thread)
    assert (run.current_node_id, run.context[CONTEXT_KEY]["then_phase"]) == ("prepare", "work")
    stale = {name: copy.deepcopy(getattr(run, name)) for name in (
        "current_node_id", "node_state", "context", "state_version")}
    await record_report(db, run, {"node_id": "prepare", "entry": run.node_state["entry"], "runtime": "device",
                                  "branch": {"state": "already"}, "environment": {"state": "not_declared"}},
                        session_id="launcher-session")
    assert run.current_node_id == "work" and run.context[CONTEXT_KEY]["node_id"] == "work"
    await db.flush()
    await db.execute(update(WorkflowRun).where(WorkflowRun.id == run.id).values(
        state_version=WorkflowRun.state_version + 1))
    db.info.pop(_CLAIMS, None)  # the report was another transaction's claim
    for name, value in stale.items():  # what this transaction read before the report committed
        set_committed_value(run, name, value)

    await _reject(db, job, UNREACHABLE)
    assert (run.current_node_id, run.status, run.node_state["waiting"]["reason"]) == (
        "work", "waiting", REASON_PLATFORM_RETRY)
    assert await _after_backoff(db, run, device) == [run.id]
    [again] = [item for item in await _jobs(db, thread) if item.id != job.id]
    assert again.status == "offered" and "phase 'Work'" in again.turn_prompt


@pytest.mark.asyncio
async def test_continue_in_a_new_chat_offers_a_refused_turn_again_in_a_fresh_session(db):
    from app.models import Session
    from app.services.workflow_runs.octryx.new_thread import continue_in_new_thread
    from app.services.workflow_runs.records import main_session_id

    admin, device, thread, run, job = await _at_work(db)
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": UNREACHABLE}, limits={})
    run.status, run.waiting_kind = "running", None
    run.node_state = {key: value for key, value in run.node_state.items() if key != "waiting"}
    run.context = {**run.context, CONTEXT_KEY: {"node_id": "work", "entry": run.node_state["entry"],
                                                "state": "started", "job_id": job.id, "phase": True}}
    run.context = {**run.context, "device_phase_sessions": {"work": {
        "node_id": "work", "claude_session_id": "claude-earlier", "device_id": device.id, "folder": job.folder,
        "profile": job.profile}}}

    fresh = await continue_in_new_thread(db, run, admin)
    assert fresh.id != thread.id and await main_session_id(db, run) == fresh.id
    assert (await db.get(Session, fresh.id)).metadata_["execution_target"]["device_id"] == device.id
    [offered] = await _jobs(db, fresh)
    assert (offered.status, offered.folder, run.status) == ("offered", job.folder, "running")
    assert offer_body(offered, limits={})["resume_session_id"] is None
    assert run.context[CONTEXT_KEY]["job_id"] == offered.id and "phase 'Work'" in offered.turn_prompt


@pytest.mark.asyncio
async def test_continue_in_a_new_chat_offers_the_turn_now_instead_of_waiting_for_the_second_offer(db):
    from app.services.workflow_runs.octryx.new_thread import continue_in_new_thread

    admin, _device, _thread, run, job = await _at_work(db)
    await _reject(db, job, UNREACHABLE)
    assert run.node_state["waiting"]["reason"] == REASON_PLATFORM_RETRY
    fresh = await continue_in_new_thread(db, run, admin)
    [offered] = await _jobs(db, fresh)
    assert (run.status, run.waiting_kind, offered.status) == ("running", None, "offered")
    assert "waiting" not in run.node_state


@pytest.mark.asyncio
async def test_continue_in_a_new_chat_leaves_a_running_turn_and_a_paused_run_alone(db):
    from app.services.workflow_runs.octryx.new_thread import continue_in_new_thread

    admin, _device, thread, run, job = await _at_work(db)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    fresh = await continue_in_new_thread(db, run, admin)
    assert await _jobs(db, fresh) == [] and job.status == "running"

    admin, _device, thread, run, job = await _at_work(db)
    await _reject(db, job, "profile_unavailable_on_device")
    assert run.status == "paused"
    fresh = await continue_in_new_thread(db, run, admin)
    assert await _jobs(db, fresh) == [] and run.status == "paused"
    assert (await db.execute(select(DeviceJob).where(DeviceJob.session_id == fresh.id))).first() is None


@pytest.mark.asyncio
async def test_a_turn_refused_by_a_full_device_waits_and_is_offered_again_until_the_limit(db, monkeypatch):
    from app.services.devices import busy_wait

    _admin, device, thread, run, job = await _at_work(db)
    await _reject(db, job, "device_busy")
    waiting = run.node_state["waiting"]
    assert (run.status, waiting["reason"]) == ("waiting", "device_busy") and run.pause_reason is None
    assert run.context[CONTEXT_KEY]["state"] == "pending"
    assert await resume_for_device(db, device.id) == []

    assert await _after_backoff(db, run, device) == [run.id]
    [again] = [item for item in await _jobs(db, thread) if item.id != job.id]
    assert (run.status, again.status) == ("running", "offered")
    assert "temporary error" not in again.turn_prompt

    await _reject(db, again, "device_busy")
    assert (run.status, run.node_state["waiting"]["reason"]) == ("waiting", "device_busy")

    monkeypatch.setattr(busy_wait, "MAX_WAIT_SECONDS", 0.0)
    assert await _after_backoff(db, run, device) == [run.id]
    [third] = [item for item in await _jobs(db, thread) if item.id not in (job.id, again.id)]
    await _reject(db, third, "device_busy")
    assert (run.status, run.pause_reason) == ("paused", "runtime_failed")
    pause = run.node_state["pause"]
    assert pause["code"] == "device_saturated" and "saturated for" in pause["message"]
    assert pause["resume"] == {"kind": "restart", "node_id": "work"}
