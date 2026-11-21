"""An alert-started Action bound to a phased workflow run (``workflow_run``) after a content-policy refusal.

A hostile alert read with ``get_run_alert`` is refused by the built-in prompt-injection policy; that refusal must not
be retried into new incident-analysis runs that nobody drives.

- **B1** a content-policy refusal is permanent (typed: the boundary's ``ContentPolicyRefusedError`` and the failed
  trace's closed ``error_class``), terminal at once, never scheduled for retry;
- **B2** a retry (or re-drive) of the same alert event never starts a second run: it continues the first one;
- **B3** a failed turn pauses the run with a typed reason (``content_blocked`` / ``runtime_failed``) and a message;
- **B4** the requester's continue on such a run re-drives the Action's turn (its main session is the automation
  identity's, which the requester cannot post into).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import FailedTaskRun, TaskRun, WorkflowRun
from app.models.runtime.audit import TurnTrace
from app.models.runtime.workflow_run import WorkflowRunEvent
from app.runtime_lifecycle import get_task_scheduler
from app.services.content_security.refusal import ContentPolicyRefusedError, with_turn_error_class
from app.services.workflow_runs.actions import available_actions
from app.services.workflow_runs.records import active_run_for_session
from tests.s5_injection_acceptance_support import _payload, _post, _workspace

# --- the alert-started Action -------------------------------------------------------------------------------------


class _Turns:
    """The fake agent turn: each call takes the next behaviour (``blocked_trace``, ``blocked_raise``, ``fail``, ``ok``)."""

    def __init__(self, *behaviours: str) -> None:
        self.behaviours = list(behaviours)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        behaviour = self.behaviours.pop(0)
        db = kwargs["db"]
        if behaviour == "blocked_raise":
            raise ContentPolicyRefusedError(("platform:prompt-injection-refused",), {"kind": "block"})
        if behaviour == "blocked_trace":
            # What the loop's runtime-failure path persists (``_loop_runtime_turn``): a failed trace with the class.
            exc = ContentPolicyRefusedError(("platform:prompt-injection-refused",), {"kind": "block"})
            db.add(TurnTrace(session_id=kwargs["session_id"], provider="runtime-fallback", model="unresolved",
                             raw_output=with_turn_error_class({"error": str(exc), "runtime_attempts": []}, exc)))
            await db.flush()
            yield SimpleNamespace(role="assistant", content=f"Agent error: {exc}", tool_results=None)
            return
        if behaviour == "fail":
            db.add(TurnTrace(session_id=kwargs["session_id"], provider="runtime-fallback", model="unresolved",
                             raw_output={"error": "provider unavailable", "runtime_attempts": []}))
            await db.flush()
            yield SimpleNamespace(role="assistant", content="Agent error: provider unavailable", tool_results=None)
            return
        yield SimpleNamespace(role="assistant", content="Reading the evidence.", tool_results=None)


@pytest.fixture
def retries(monkeypatch):
    scheduled: list[dict] = []
    monkeypatch.setattr(get_task_scheduler(), "_schedule_failed_task_retry", lambda **kwargs: scheduled.append(kwargs))
    return scheduled


async def _alert_action(client, db, monkeypatch, turns: _Turns) -> dict:
    admin, project, task, created = await _workspace(db, bearer=False)
    monkeypatch.setattr("app.agent.engine.run_agent", turns)
    response = await _post(client, created, _payload(hostile=True), bearer=False)
    assert response.status_code == 202, response.text
    accepted = response.json()
    await get_task_scheduler()._execute_task(task.id, task_run_id=accepted["task_run_id"], trigger_type="webhook",
                                             trigger_id=created["id"])
    task_run = await db.get(TaskRun, accepted["task_run_id"])
    await db.refresh(task_run)
    return {"admin": admin, "project": project, "task": task, "webhook": created, "task_run": task_run}


async def _runs(db, task) -> list[WorkflowRun]:
    run_ids = (await db.execute(
        select(WorkflowRunEvent.run_id).where(WorkflowRunEvent.kind == "started_by_action")
    )).scalars().all()
    runs = [await db.get(WorkflowRun, run_id) for run_id in run_ids]
    found = [run for run in runs if run is not None and run.project_id == task.project_id]
    for run in found:
        await db.refresh(run)
    return found


async def _execute_retry(db, task, scheduled: dict) -> TaskRun:
    """What the retry job does (``_schedule_failed_task_retry``): queue the Action as a retry, then run it."""
    queued = await get_task_scheduler().run_task_now(
        scheduled["task_id"], trigger_type="retry", trigger_id=scheduled["failed_task_run_id"],
        started_by=scheduled.get("started_by"), run_input=scheduled.get("run_input"))
    await get_task_scheduler()._execute_task(task.id, task_run_id=queued["task_run_id"], trigger_type="retry",
                                             trigger_id=scheduled["failed_task_run_id"])
    retry = await db.get(TaskRun, queued["task_run_id"])
    await db.refresh(retry)
    return retry


@pytest.mark.asyncio
@pytest.mark.parametrize("behaviour", ["blocked_trace", "blocked_raise"])
async def test_a_content_refused_alert_turn_leaves_one_paused_run_and_no_retry(
    client, db, monkeypatch, retries, behaviour
):
    case = await _alert_action(client, db, monkeypatch, _Turns(behaviour))
    task_run, task = case["task_run"], case["task"]

    # Terminal, typed, nothing scheduled.
    assert task_run.status == "error" and task_run.error == "content_blocked"
    decision = task_run.output["failure_decision"]
    assert decision["status"] == "content_blocked" and decision["retryable"] is False and decision["terminal"] is True
    assert retries == []
    failed = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_id == task.id))).scalars().all()
    assert [row.status for row in failed] == ["content_blocked"] and failed[0].next_retry_at is None

    # B2/B3: exactly one run, paused with the typed reason and an actionable message.
    runs = await _runs(db, task)
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "paused" and run.pause_reason == "content_blocked"
    pause = run.node_state["pause"]
    assert "content policy refused" in pause["message"].lower() and "abort" in pause["message"]
    assert pause["task_run_id"] == task_run.id and pause["retry_scheduled"] is False
    assert task_run.output["workflow_run"] == {"run_id": run.id, "status": "paused", "pause_reason": "content_blocked"}
    keys = [action["key"] for action in await available_actions(db, run, access="write", user=case["admin"])]
    assert {"continue", "abort", "resume_in_new_session"} <= set(keys)


@pytest.mark.asyncio
async def test_a_retry_of_a_failed_alert_turn_continues_the_same_run(client, db, monkeypatch, retries):
    turns = _Turns("fail", "ok")
    case = await _alert_action(client, db, monkeypatch, turns)
    task_run, task = case["task_run"], case["task"]

    # A runtime failure stays retryable; the run pauses typed and says a retry continues it.
    assert task_run.status == "error" and task_run.output["failure_decision"]["retryable"] is True
    assert len(retries) == 1 and retries[0]["run_input"]["inbound_alert"]["event_id"]
    [run] = await _runs(db, task)
    assert run.status == "paused" and run.pause_reason == "runtime_failed"
    assert run.node_state["pause"]["retry_scheduled"] is True

    retry = await _execute_retry(db, task, retries[0])

    assert retry.status == "success", retry.output
    runs = await _runs(db, task)
    assert [item.id for item in runs] == [run.id], "a retry never starts a second run"
    await db.refresh(run)
    assert run.status == "running" and run.pause_reason is None
    bound = await active_run_for_session(db, retry.session_id)
    assert bound is not None and bound.id == run.id
    kinds = (await db.execute(select(WorkflowRunEvent.kind, WorkflowRunEvent.detail)
                              .where(WorkflowRunEvent.run_id == run.id))).all()
    reused = [detail for kind, detail in kinds if kind == "action_run_reused"]
    assert len(reused) == 1 and reused[0]["task_run_id"] == retry.id and reused[0]["trigger_type"] == "retry"
    assert any(kind == "resumed" and detail.get("from") == "runtime_failed" for kind, detail in kinds)
    assert len(turns.calls) == 2


@pytest.mark.asyncio
async def test_a_retry_after_the_run_ended_starts_nothing_and_is_terminal(client, db, monkeypatch, retries):
    from app.services.workflow_runs.pause import abort_run

    case = await _alert_action(client, db, monkeypatch, _Turns("fail", "ok"))
    task = case["task"]
    [run] = await _runs(db, task)
    await abort_run(db, run, user=case["admin"], reason="handled elsewhere")
    await db.commit()
    retries_before = list(retries)

    retry = await _execute_retry(db, task, retries_before[0])

    assert retry.status == "error" and retry.error == "action_workflow_run_ended"
    assert retry.output["failure_decision"]["status"] == "admission_refused"
    assert len(retries) == 1, "the refusal is terminal"
    assert [item.id for item in await _runs(db, task)] == [run.id]


@pytest.mark.asyncio
async def test_continue_on_a_paused_alert_run_re_drives_the_action_turn(
    client, db, monkeypatch, retries, auth_headers
):
    turns = _Turns("blocked_trace", "ok")
    case = await _alert_action(client, db, monkeypatch, turns)
    task, first = case["task"], case["task_run"]
    [run] = await _runs(db, task)
    assert run.pause_reason == "content_blocked"
    queued: list[dict] = []
    scheduler = get_task_scheduler()
    original = scheduler.run_task_now

    async def capture(*args, **kwargs):
        queued.append(kwargs)
        return await original(*args, **kwargs)

    monkeypatch.setattr(scheduler, "run_task_now", capture)

    response = await client.post(f"/api/v1/workflow-runs/{run.id}/actions", headers=auth_headers,
                                 json={"action": "continue"})

    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "running"
    assert len(queued) == 1
    redrive = queued[0]
    assert redrive["trigger_type"] == "workflow_continue" and redrive["trigger_id"] == run.id
    assert redrive["started_by"] == first.started_by != case["admin"].id  # the automation identity, not the owner
    assert redrive["run_input"]["workflow_run_id"] == run.id
    assert redrive["run_input"]["inbound_alert"]["event_id"] == first.input_["inbound_alert"]["event_id"]
    task_run_id = (await db.execute(select(TaskRun.id).where(TaskRun.trigger_type == "workflow_continue",
                                                             TaskRun.task_id == task.id))).scalar_one()

    await scheduler._execute_task(task.id, task_run_id=task_run_id, trigger_type="workflow_continue",
                                  trigger_id=run.id)

    again = await db.get(TaskRun, task_run_id)
    await db.refresh(again)
    assert again.status == "success", again.output
    assert len(turns.calls) == 2 and "This run was started by an alert." in turns.calls[1]["user_message"]
    assert [item.id for item in await _runs(db, task)] == [run.id]
    bound = await active_run_for_session(db, again.session_id)
    assert bound is not None and bound.id == run.id
    await db.refresh(run)
    assert run.context["action_redrive"]["state"] == "queued"
    redriven = (await db.execute(select(func.count()).select_from(WorkflowRunEvent).where(
        WorkflowRunEvent.run_id == run.id, WorkflowRunEvent.kind == "action_turn_redriven"))).scalar_one()
    assert redriven == 1
