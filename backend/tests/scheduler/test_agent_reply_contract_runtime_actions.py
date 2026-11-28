"""Contract: Actions of a checked-reply agent succeed only on their run's satisfied final reply."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.scheduler.execution.task_run_finish as task_run_finish
from app.models import FailedTaskRun, Task, TaskDependency, TaskQueueEntry, TaskRun
from app.scheduler import TaskScheduler
from app.scheduler.execution._step_agent_loader import load_agent_for_step
from app.services.agent_definition_execution_outcomes import AgentDefinitionExecutionError
from app.time_utils import utc_now
from tests.scheduler.test_action_runtime_admission import _admin, _agent, _project
from tests.scripted_pool_support import (
    scripted_pool,  # noqa: F401 - fixture
    scripted_turns,  # noqa: F401 - fixture
)
from tests.support.agent_reply_contract_runtime_actions_support import (
    CONTRACT,
    FINISHED_SATISFIED,
    INTERMEDIATE,
    NOT_JSON,
    SATISFIED,
    STOPPED_NOT_JSON,
    UNCHECKED,
    _action,
    _foreign_chat_turn,
    _session,
    _single_session,
    _trace,
    _write_run,
)

pytestmark = [pytest.mark.usefixtures("scripted_turns"), pytest.mark.usefixtures("scripted_pool")]


async def _run(db, monkeypatch, task, *, run=(), reuse=None, foreign_turn=False):
    import app.db as database_module

    calls: list[str] = []
    retries: list[dict] = []
    webhooks: list[str] = []

    async def fake_run_agent_for_task(db_, task_, prompt, *, on_session_ready=None, **kwargs):
        calls.append(prompt)
        session = reuse or await _session(db_, task_.owner_id)
        if on_session_ready is not None:
            await on_session_ready(session)
        if foreign_turn:
            await _foreign_chat_turn(db_, session.id)
        await _write_run(db_, session.id, run)
        return session, {"session_id": session.id, "response": "Summary: all good"}

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
    await db.refresh(entry)
    failures = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_id == task.id))).scalars().all()
    return SimpleNamespace(run=run_row, entry=entry, failures=failures, calls=calls, retries=retries,
                           webhooks=webhooks)


async def test_a_satisfied_checked_reply_succeeds_and_emits_task_completed(db, monkeypatch):
    task, _agent_row = await _action(db, reply_contract=CONTRACT)
    result = await _run(db, monkeypatch, task, run=[INTERMEDIATE, FINISHED_SATISFIED])
    assert (result.run.status, result.run.error, result.run.output["reply_contract"]) == ("success", None, SATISFIED)
    assert result.failures == [] and result.webhooks == ["task.completed"]


async def test_a_violated_checked_reply_fails_terminally_emits_task_failed_and_skips_dependents(db, monkeypatch):
    task, _agent_row = await _action(db, reply_contract=CONTRACT)
    downstream, _other = await _action(db, name="Publish summary")
    db.add(TaskDependency(task_id=downstream.id, depends_on_task_id=task.id, condition="success"))
    await db.commit()

    result = await _run(db, monkeypatch, task, run=[STOPPED_NOT_JSON])

    assert len(result.calls) == 1 and result.retries == [], "one turn, no retry scheduled"
    assert (result.run.status, result.run.error) == ("error", "agent_reply_not_json")
    assert result.run.output["response"] == "Summary: all good" and result.run.output["reply_contract"] == NOT_JSON
    [failure] = result.failures
    assert (failure.status, failure.next_retry_at, failure.last_error) == (
        "reply_contract_violation", None, "agent_reply_not_json")
    assert (result.entry.status, result.entry.next_retry_at) == ("failed", None)
    decision = result.run.output["failure_decision"]
    assert (decision["reason"], decision["terminal"], decision["retryable"]) == (
        "agent_reply_contract_violation", True, False)
    assert decision["retry_policy"] == {"name": "reply_contract_violation", "delays_seconds": [],
                                        "max_retry_attempts": 0}
    assert result.webhooks == ["task.failed"]

    dependent = await _run(db, monkeypatch, downstream, run=[FINISHED_SATISFIED])
    assert dependent.calls == [], "a success-only dependent never runs after the refused reply"
    assert (dependent.run.status, dependent.run.output["status"]) == ("skipped", "blocked_by_dependencies")


async def test_a_reused_session_with_an_older_finished_trace_does_not_count(db, monkeypatch):
    task, _agent_row = await _action(db, reply_contract=CONTRACT)
    reused = await _session(db, task.owner_id)
    await _trace(db, reused.id, at=utc_now() - timedelta(minutes=10), **FINISHED_SATISFIED)
    await db.commit()

    # This run writes no trace (iteration-budget fallback), so nothing of the run was checked.
    result = await _run(db, monkeypatch, task, run=[], reuse=reused)

    assert (result.run.status, result.run.error, result.run.output["reply_contract"]) == ("error", UNCHECKED, None)
    assert result.retries == [] and result.webhooks == ["task.failed"]


async def test_a_text_agent_keeps_the_existing_success_rule(db, monkeypatch):
    # The checked-reply rule never applies to a text agent: a finish without any reply record succeeds.
    # (A text agent's recorded runtime stop is covered in ``test_action_stopped_turn_outcome.py``.)
    task, _agent_row = await _action(db)
    result = await _run(db, monkeypatch, task, run=[{"outcome": "finished"}])
    assert (result.run.status, result.run.error, result.failures) == ("success", None, [])
    assert "reply_contract" not in result.run.output and result.webhooks == ["task.completed"]


async def test_a_step_refuses_a_checked_agent_before_any_model_call(db):
    task, agent = await _action(db, reply_contract=CONTRACT)
    step = SimpleNamespace(connector_params={"agent_definition_id": agent.id}, runtime_selector={})
    with pytest.raises(AgentDefinitionExecutionError) as refused:
        await load_agent_for_step(step, task, db, logging.getLogger(__name__))
    assert refused.value.code == "agent_reply_contract_path_unsupported"
    assert refused.value.as_metadata()["definition_id"] == agent.id


@pytest.mark.parametrize(("checked", "failure_status"), [(True, "admission_refused"), (False, "pending_retry")])
async def test_only_the_reply_format_step_refusal_is_terminal(db, monkeypatch, checked, failure_status):
    from app.models.project.task import TaskStep

    fields = {"reply_contract_json": json.dumps(CONTRACT)} if checked else {"is_active": False}
    project = await _project(db, f"reply-steps-{uuid.uuid4().hex[:6]}")
    owner = await _admin(db)
    agent = await _agent(db, owner.id, project.id, **fields)
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project.id, name="Relay", task_type="webhook_relay",
                agent_type="diagnosis", owner_id=owner.id, is_active=True, config={})
    db.add(task)
    db.add(TaskStep(task_id=task.id, position=1, name="Analyse", step_type="analysis", is_enabled=True,
                    connector_params_json=json.dumps({"agent_definition_id": agent.id})))
    await db.commit()

    result = await _run(db, monkeypatch, task)

    assert result.calls == [] and result.run.status == "error"
    [failure] = result.failures
    assert failure.status == failure_status
    if checked:
        assert result.run.error == "agent_reply_contract_path_unsupported" and result.retries == []


async def test_a_foreign_chat_turn_after_the_boundary_never_supplies_the_runs_success(db, monkeypatch):
    task, _agent_row = await _action(db, reply_contract=CONTRACT)

    # The run itself records no outcome; a chat turn on the reused session writes a satisfied final.
    result = await _run(db, monkeypatch, task, run=[], foreign_turn=True)

    assert (result.run.status, result.run.error) == ("error", UNCHECKED)
    assert result.retries == [] and result.webhooks == ["task.failed"]


