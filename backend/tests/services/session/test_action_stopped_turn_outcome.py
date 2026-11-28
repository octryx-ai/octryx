"""An Action of a free-text agent whose turn the runtime recorded as ``stopped`` is a terminal ``error``, not a
success; every other case keeps the text-based failure rule."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.scheduler.execution.task_run_finish as task_run_finish
from app.models import FailedTaskRun, TaskDependency, TaskQueueEntry, TaskRun
from app.scheduler import TaskScheduler
from app.services.session.turn_final_outcome import TurnFinalOutcome, action_stop_verdict
from app.time_utils import utc_now
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)
from tests.support.agent_reply_contract_runtime_actions_support import (
    FINISHED_SATISFIED,
    INTERMEDIATE,
    _action,
    _foreign_chat_turn,
    _session,
    _single_session,
    _trace,
    _write_run,
)

pytestmark = [pytest.mark.usefixtures("scripted_turns"), pytest.mark.usefixtures("scripted_pool")]

STOPPED = {"outcome": "stopped", "stop_reason": "answer_evidence_invented_url"}
FINISHED = {"outcome": "finished"}
OK_RESPONSE = "Summary: all good"


@pytest.mark.parametrize(("final", "verdict"), [
    (TurnFinalOutcome("t", "stopped", "answer_evidence_invented_url", None), "answer_evidence_invented_url"),
    (TurnFinalOutcome("t", "stopped", "step_tool_required", None), "step_tool_required"),
    (TurnFinalOutcome("t", "stopped", None, None), None),
    (TurnFinalOutcome("t", "stopped", "model_said_so", None), None),
    (TurnFinalOutcome("t", "finished", None, None), None),
    (TurnFinalOutcome("t", "failed", None, None), None),
    # A failed trace (``raw_output.error``) keeps the old rule even if it also carries a stop marker.
    (TurnFinalOutcome("t", "failed", "step_tool_required", None), None),
    (TurnFinalOutcome("t", "finished", "step_tool_required", None), None),
    (None, None),
])
def test_only_a_recorded_stop_with_a_closed_reason_is_a_verdict(final, verdict):
    assert action_stop_verdict(final) == verdict


async def _run(db, monkeypatch, task, *, run=(), reuse=None, foreign_turn=False, response=OK_RESPONSE):
    import app.db as database_module

    calls: list[str] = []
    retries: list[dict] = []
    webhooks: list[str] = []

    async def fake_run_agent_for_task(db_, task_, prompt, *, on_session_ready=None, **kwargs):
        calls.append(prompt)
        session = reuse or await _session(db_, task_.owner_id)
        await on_session_ready(session)
        if foreign_turn:
            await _foreign_chat_turn(db_, session.id)
        await _write_run(db_, session.id, run)
        return session, {"session_id": session.id, "response": response}

    async def fake_webhook(db_, *, event_type, **kwargs):
        webhooks.append(event_type)

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    monkeypatch.setattr(scheduler, "_schedule_failed_task_retry", lambda **kwargs: retries.append(kwargs))
    monkeypatch.setattr(task_run_finish, "emit_outbound_webhook_event", fake_webhook)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="manual")
    run_row = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == run_row.id))).scalar_one()
    await db.refresh(run_row)
    failures = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_id == task.id))).scalars().all()
    return SimpleNamespace(run=run_row, entry=entry, failures=failures, calls=calls, retries=retries,
                           webhooks=webhooks)


async def test_a_stopped_text_turn_fails_terminally_and_skips_success_only_dependents(db, monkeypatch):
    task, _agent_row = await _action(db)
    downstream, _other = await _action(db, name="Publish summary")
    db.add(TaskDependency(task_id=downstream.id, depends_on_task_id=task.id, condition="success"))
    await db.commit()

    result = await _run(db, monkeypatch, task, run=[INTERMEDIATE, STOPPED])

    assert (result.run.status, result.run.error) == ("error", "answer_evidence_invented_url")
    assert result.run.output["response"] == OK_RESPONSE, "the raw response is kept"
    assert result.run.output["turn_outcome"] == {"state": "stopped", "reason": "answer_evidence_invented_url"}
    [failure] = result.failures
    assert (failure.status, failure.next_retry_at, result.entry.status) == ("runtime_stopped", None, "failed")
    decision = result.run.output["failure_decision"]
    assert (decision["reason"], decision["terminal"], decision["retryable"]) == (
        "agent_turn_runtime_stopped", True, False)
    assert decision["retry_policy"] == {"name": "runtime_stopped", "delays_seconds": [], "max_retry_attempts": 0}
    assert result.retries == [] and result.webhooks == ["task.failed"]

    dependent = await _run(db, monkeypatch, downstream, run=[FINISHED])
    assert dependent.calls == [] and (dependent.run.status, dependent.run.output["status"]) == (
        "skipped", "blocked_by_dependencies")


async def test_a_finished_text_turn_still_succeeds(db, monkeypatch):
    task, _agent_row = await _action(db)
    result = await _run(db, monkeypatch, task, run=[INTERMEDIATE, FINISHED])
    assert (result.run.status, result.run.error, result.failures, result.webhooks) == (
        "success", None, [], ["task.completed"])
    assert "turn_outcome" not in result.run.output


@pytest.mark.parametrize("case", ["no-trace", "unrecorded", "several-finals", "failed-outcome", "foreign-turn"])
async def test_anything_but_the_runs_own_stop_keeps_the_text_rule(db, monkeypatch, case):
    task, _agent_row = await _action(db)
    run, foreign = {
        "no-trace": ([], False),
        "unrecorded": ([INTERMEDIATE], False),
        "several-finals": ([STOPPED, FINISHED], False),
        "failed-outcome": ([{"outcome": "failed"}], False),
        "foreign-turn": ([STOPPED], True),
    }[case]

    result = await _run(db, monkeypatch, task, run=run, foreign_turn=foreign)

    assert (result.run.status, result.run.error, result.webhooks) == ("success", None, ["task.completed"])
    assert "turn_outcome" not in result.run.output


async def test_the_text_rule_still_detects_its_own_failures_and_retries_them(db, monkeypatch):
    task, _agent_row = await _action(db)
    result = await _run(db, monkeypatch, task, run=[INTERMEDIATE], response="Agent error: provider unavailable")
    assert result.run.status == "error" and "turn_outcome" not in result.run.output
    [failure] = result.failures
    assert failure.status == "pending_retry" and result.webhooks == ["task.failed"]


async def test_an_older_stopped_trace_on_a_reused_session_never_fails_a_new_run(db, monkeypatch):
    task, _agent_row = await _action(db)
    reused = await _session(db, task.owner_id)
    await _trace(db, reused.id, at=utc_now() - timedelta(minutes=10), **STOPPED)
    await db.commit()

    for run in ([INTERMEDIATE, FINISHED], []):
        result = await _run(db, monkeypatch, task, run=run, reuse=reused)
        assert (result.run.status, result.run.error, result.webhooks) == ("success", None, ["task.completed"])


async def test_an_older_stop_is_the_sessions_only_trace_and_a_trace_less_run_still_succeeds(db, monkeypatch):
    task, _agent_row = await _action(db)
    reused = await _session(db, task.owner_id)
    await _trace(db, reused.id, at=utc_now() - timedelta(minutes=10), **STOPPED)
    await db.commit()

    result = await _run(db, monkeypatch, task, run=[], reuse=reused)

    assert (result.run.status, result.run.error, result.webhooks) == ("success", None, ["task.completed"])
    assert "turn_outcome" not in result.run.output and result.failures == []


async def test_a_checked_agent_keeps_the_1178_rule(db, monkeypatch):
    from tests.support.agent_reply_contract_runtime_actions_support import CONTRACT

    task, _agent_row = await _action(db, reply_contract=CONTRACT)
    result = await _run(db, monkeypatch, task, run=[FINISHED_SATISFIED])
    assert (result.run.status, "turn_outcome" in result.run.output) == ("success", False)


