"""Pausing a phase turn that ends unfinished or keeps asking, aborting a running turn, and the pause and fix-prompt texts it leaves."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session, UserDevice
from app.services.devices.job_events import apply_event
from app.services.devices.jobs import start_turn
from app.services.workflow_runs.octryx.continuation_marker import CONTEXT_KEY
from tests.workflow_run_octryx_continuation_support import (  # noqa: F401
    FOLDER,
    _confirm,
    _device_run,
    _hub,
    _jobs,
    _reenter,
)


def _ended_unfinished_once(run) -> None:
    """The pass already ended unfinished once: the second time (stall_after, default 2) pauses (the
    first time it goes on by itself, tests/test_platform_evidence.py)."""
    from app.services.workflow_runs.octryx.same_pass import UNFINISHED_KEY

    run.context = {**dict(run.context or {}), UNFINISHED_KEY: {
        "node_id": run.current_node_id, "entry": dict(run.node_state or {}).get("entry"), "times": 1}}


_COF49_STYLE = {"type": "code_style", "outcome": "failed", "blocking": True,
                "description": "Code style of the installation",
                "detail": "system_test/run_system_test.py: was already over the limit (585) and grew to 657 (max 500): "
                          "put the new code into a new module [tests_max_lines]"}


async def _user_texts(db, thread: Session) -> list[str]:
    from app.models import Message

    rows = (await db.execute(select(Message.content).where(Message.session_id == thread.id, Message.role == "user")
                             .order_by(Message.created_at))).scalars().all()
    return [str(text or "") for text in rows]


@pytest.mark.asyncio
async def test_a_phase_turn_that_ends_unfinished_pauses_and_a_users_own_failed_turn_does_not(db):
    """A phase turn that ends without its checks must not leave the run 'running'. It pauses with the agent's
    words; a turn the user typed afterwards changes nothing."""
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    _ended_unfinished_once(run)
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                 "result_text": "The test file can't be created."}, limits={})
    assert (run.status, run.pause_reason) == ("paused", "phase_not_finished")
    assert run.node_state["pause"]["code"] == "phase_not_finished"
    assert "can't be created" in run.node_state["pause"]["message"]

    # A turn the user typed afterwards (no continuation of this pass is started any more) fails: no new pause.
    run.status, run.pause_reason = "running", None
    run.context = {key: value for key, value in run.context.items() if key != CONTEXT_KEY}
    own = await start_turn(db, owner_user_id=admin.id, device=await db.get(UserDevice, job.device_id),
                           session_id=thread.id, workspace_id=thread.project_id, folder=FOLDER, profile="governed",
                           prompt="my own question")
    await apply_event(db, own, "turn_finished", {"turn_id": own.turn_id, "status": "error"}, limits={})
    assert (run.status, run.pause_reason) == ("running", None)


@pytest.mark.asyncio
async def test_a_phase_turn_asking_again_after_three_refused_approvals_pauses_the_run(db):
    import time

    from sqlalchemy import update

    from app.models import DeviceJobApproval

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})

    async def ask(n: int) -> None:
        await apply_event(db, job, "approval_request", {
            "turn_id": job.turn_id, "approval_id": f"ap{n}", "tool": "Edit", "input_preview": f"{FOLDER}/t.py",
            "expires_at": time.time() + 300}, limits={"approval_timeout_s": 300})

    for n in range(3):
        await ask(n)
        assert run.status == "running"
        await db.execute(update(DeviceJobApproval).where(DeviceJobApproval.job_id == job.id,
                                                         DeviceJobApproval.status == "pending").values(status="expired"))
    await ask(3)
    assert (run.status, run.pause_reason) == ("paused", "approval_timeout")
    assert run.node_state["pause"]["code"] == "device_approvals_unanswered"
    assert run.node_state["pause"]["resume"] == {"kind": "restart", "node_id": "work"}
    assert job.stop_state == "pending" and CONTEXT_KEY not in run.context


@pytest.mark.asyncio
async def test_aborting_a_run_stops_its_running_device_turn(db):
    from app.services.workflow_runs.pause import abort_run

    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await abort_run(db, run, user=admin, reason="not needed")
    assert run.status == "stopped" and job.stop_state == "pending"


@pytest.mark.asyncio
async def test_the_pause_of_an_unfinished_phase_turn_names_the_check_that_failed(db):
    """A turn judged failed by the code style (a file over its size limit) must not pause with only "its checks did
    not pass": the failed check is named (honesty rule)."""
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    _ended_unfinished_once(run)
    advisory = {"type": "test_command_passed", "outcome": "failed", "blocking": False,
                "description": "The last test run after the last change passed", "detail": "no_test_after_last_change"}
    run.gate_results = {run.current_node_id: {"state": "failed", "results": [
        {"type": "tool_called", "outcome": "passed", "blocking": True, "description": "The test suite ran",
         "detail": ""}, advisory, _COF49_STYLE]}}
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success",
                                                 "result_text": "Everything is green."}, limits={})
    pause = run.node_state["pause"]
    assert pause["code"] == "phase_not_finished"
    assert "Code style of the installation: system_test/run_system_test.py" in pause["message"]
    assert "[tests_max_lines]" in pause["message"] and "no_test_after_last_change" not in pause["message"]
    assert [item["type"] for item in pause["failed_checks"]] == ["code_style"]


def test_a_failed_turn_without_a_failed_blocking_check_says_so():
    from app.services.workflow_checks.library import CheckResult
    from app.services.workflow_runs.binding import failed_checks, failed_checks_text

    passed = CheckResult(type="tool_called", outcome="passed", blocking=True, description="ran", detail="")
    assert failed_checks_text(failed_checks([passed])) == "no blocking check is recorded as failed for this turn"
    style = CheckResult(**_COF49_STYLE)
    assert failed_checks([passed, style]) == [{"type": "code_style", "description": _COF49_STYLE["description"],
                                               "detail": _COF49_STYLE["detail"]}]


@pytest.mark.asyncio
async def test_a_green_pipeline_leaves_no_red_fix_prompt_in_the_chat_and_a_red_one_shows_it_with_its_turn(db):
    """A device run with a green pipeline must not end in the chat with "the CI pipeline ran … and they are red …
    Fix exactly that": the prompt is stored when the turn is offered, before the launcher knows the result, and
    must not stay when it ends the job green (``pipeline_done``). It reaches the chat only at ``job_accepted``."""
    admin, _device, thread, run = await _device_run(db)
    await _confirm(db, run, admin)
    [job] = await _jobs(db, thread)
    await apply_event(db, job, "job_event", {"kind": "session", "claude_session_id": "claude-work-1"}, limits={})
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})
    await apply_event(db, job, "turn_finished", {"turn_id": job.turn_id, "status": "success"}, limits={})
    before = await _user_texts(db, thread)

    await _reenter(db, run, "work", runtime_step=True)  # the pipeline turn
    await _reenter(db, run, "work")  # its continuation into the phase, offered before the result is known
    await apply_event(db, job, "job_rejected", {"turn_id": job.turn_id, "reason": "pipeline_done"}, limits={})
    green = await _user_texts(db, thread)
    assert green[: len(before)] == before
    assert not any("red" in text and "pipeline" in text.lower() for text in green[len(before):])

    await _reenter(db, run, "work", runtime_step=True)
    await _reenter(db, run, "work")
    prompt = job.turn_prompt
    await apply_event(db, job, "job_accepted", {"turn_id": job.turn_id}, limits={})  # red: the agent's turn starts
    red = await _user_texts(db, thread)
    assert red[-1] == prompt and red.count(prompt) == 1
