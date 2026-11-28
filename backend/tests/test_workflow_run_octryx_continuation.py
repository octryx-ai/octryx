"""octryx run UX: the next phase continues on the device without a manual prompt."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import UserDevice
from app.services.devices.hub import device_hub
from app.services.devices.job_events import apply_event
from app.services.devices.job_offer import offer_body
from app.services.devices.jobs import start_turn
from app.services.workflow_runs.limits import pause_run
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from tests.scripted_pool_support import scripted_pool  # noqa: F401 - fixture
from tests.workflow_run_octryx_continuation_support import FOLDER, _confirm, _device_run, _hub, _jobs  # noqa: F401

pytestmark = pytest.mark.usefixtures("scripted_pool")


@pytest.mark.asyncio
async def test_a_decision_starts_the_next_phase_on_the_device_thread(db):
    admin, device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    assert run.current_node_id == "work"
    [job] = await _jobs(db, thread)
    assert (job.device_id, job.folder, job.status) == (device.id, FOLDER, "offered")
    assert "phase 'Work'" in job.turn_prompt and "workflow_run_status" in job.turn_prompt
    assert run.context[CONTEXT_KEY]["state"] == "started" and run.context[CONTEXT_KEY]["job_id"] == job.id


@pytest.mark.asyncio
async def test_a_busy_turn_hands_over_when_it_finishes_and_a_paused_run_never_continues(db):
    admin, device, thread, run = await _device_run(db)
    busy = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                            session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                            prompt="the turn still running")
    await _confirm(db, run, admin)
    assert run.context[CONTEXT_KEY]["state"] == "pending" and busy.turn_count == 1
    await apply_event(db, busy, "turn_finished", {"turn_id": busy.turn_id, "status": "success"}, limits={})
    assert busy.status == "offered" and busy.turn_count == 2 and "phase 'Work'" in busy.turn_prompt
    assert run.context[CONTEXT_KEY]["state"] == "started"

    admin, device, thread, run = await _device_run(db)
    busy = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                            session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                            prompt="the turn still running")
    await _confirm(db, run, admin)
    await pause_run(db, run, reason="budget_limit", actor_id=None, detail={"message": "budget used"})
    await apply_event(db, busy, "turn_finished", {"turn_id": busy.turn_id, "status": "success"}, limits={})
    assert busy.status == "idle" and busy.turn_count == 1 and CONTEXT_KEY not in run.context


@pytest.mark.asyncio
async def test_a_thread_without_a_device_runs_its_phase_on_the_pool(db):
    from tests.scripted_pool_support import RUNNER_ID

    admin, _device, thread, run = await _device_run(db, on_device=False)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    assert run.current_node_id == "work" and job.device_id == RUNNER_ID and run.context[CONTEXT_KEY]["state"] == "started"


@pytest.mark.asyncio
async def test_a_failed_turn_hands_over_too_and_the_turn_is_marked_as_the_platforms(db):
    from app.models import Message
    from app.services.workflow_runs.octryx.continuation_marker import PROVENANCE

    admin, device, thread, run = await _device_run(db)
    busy = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, device.id),
                            session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                            prompt="the turn still running")
    await _confirm(db, run, admin)
    await apply_event(db, busy, "job_failed", {"turn_id": busy.turn_id, "reason": "claude_crashed"}, limits={})
    jobs = await _jobs(db, thread)
    assert run.context[CONTEXT_KEY]["state"] == "started" and any(job.status == "offered" for job in jobs)
    platform = select(Message).where(Message.session_id == thread.id, Message.idempotency_key.like(f"{PROVENANCE}:%"))
    assert (await db.execute(platform)).scalars().all() == []
    offered_job = next(job for job in jobs if job.status == "offered")
    await apply_event(db, offered_job, "job_accepted", {"turn_id": offered_job.turn_id}, limits={})
    [message] = (await db.execute(platform)).scalars()
    assert "phase 'Work'" in message.content
    offered = db.sync_session.info.get("workflow_continuation_offered")
    assert offered and offered[-1][1]["eventType"] == "turn_offered"


@pytest.mark.asyncio
async def test_a_refused_continuation_is_visible_in_the_contract(db):
    from app.services.workflow_runs.octryx.contract import run_contract

    admin, device, thread, run = await _device_run(db)
    thread.metadata_ = {**thread.metadata_, "execution_target": {**thread.metadata_["execution_target"],
                                                                 "folder": "/home/elsewhere"}}
    await _confirm(db, run, admin)
    continuation = (await run_contract(db, run))["phase"]["continuation"]
    assert continuation == {"state": "refused", "reason": "folder_not_allowlisted"}


@pytest.mark.asyncio
async def test_an_offline_device_holds_the_run_waiting_for_device_with_the_turn_still_pending(db):
    from app.services.workflow_runs.octryx.contract import run_contract

    admin, device, thread, run = await _device_run(db)
    device_hub.clear()
    await _confirm(db, run, admin)
    assert (run.status, run.waiting_kind, run.current_node_id) == ("waiting", "waiting_for_device", "work")
    assert run.context[CONTEXT_KEY]["state"] == "pending" and await _jobs(db, thread) == []
    assert (await run_contract(db, run))["waiting"]["kind"] == "waiting_for_device"


@pytest.mark.asyncio
async def test_a_failed_phase_turn_pauses_the_run_instead_of_leaving_it_running(db):
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "error",
                                                 "error": "claude_crashed"}, limits={})
    assert (run.status, run.pause_reason, run.current_node_id) == ("paused", "turn_failed", "work")
    pause = run.node_state["pause"]
    assert pause["code"] == "device_turn_claude_crashed"
    assert pause["resume"] == {"kind": "restart", "node_id": "work"} and CONTEXT_KEY not in run.context


@pytest.mark.asyncio
async def test_a_temporary_model_service_error_runs_the_phase_once_more_by_itself(db):
    from datetime import timedelta

    from app.services.workflow_runs.runtime_target.device_wait import REASON_MODEL_RETRY, resume_for_device
    from app.time_utils import utc_now

    admin, device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    job.claude_session_id = "claude-work-pass"
    await apply_event(db, job, "turn_finished", {
        "turn_id": job.turn_id, "status": "error",
        "result_text": 'API Error: 503 {"error":"no available server"}'}, limits={})
    waiting = run.node_state["waiting"]
    assert (run.status, run.waiting_kind, waiting["reason"]) == ("waiting", "waiting_for_device", REASON_MODEL_RETRY)
    assert run.context[CONTEXT_KEY]["state"] == "pending" and job.turn_count == 1
    assert await resume_for_device(db, device.id) == []

    run.node_state = {**run.node_state, "waiting": {**waiting, "retry_after": (
        utc_now() - timedelta(seconds=1)).isoformat()}}
    assert await resume_for_device(db, device.id) == [run.id]
    assert run.status == "running" and job.status == "offered" and job.turn_count == 2
    assert offer_body(job, limits={})["resume_session_id"] == "claude-work-pass"
    assert "temporary error" in job.turn_prompt and "workflow_run_status" not in job.turn_prompt

    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "error",
                                                 "result_text": "API Error: 529 overloaded"}, limits={})
    assert (run.status, run.pause_reason) == ("paused", "turn_failed")


def test_only_model_service_and_gateway_errors_count_as_temporary():
    from app.services.workflow_runs.octryx.turn_failures import is_transient_failure

    for said in ("API Error: 503 no available server", "API Error: 500 Internal server error",
                 "Overloaded", "Request timed out.", "API Error: Connection error."):
        assert is_transient_failure("error", said), said
    assert is_transient_failure("api_error_504", "")
    assert not is_transient_failure("error", "The test file can't be created.")
    assert is_transient_failure("service_restarted", "") and is_transient_failure("turn_stalled", "")
    assert not is_transient_failure("error", "You've hit your weekly limit · resets Nov 13 at 11am")
