"""Contract: a run refused by execution admission is terminal at once and never retried."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import FailedTaskRun, Task, TaskQueueEntry, TaskRun
from app.scheduler import TaskScheduler
from app.scheduler.execution import task_run_kinds
from app.services.admin.provider.admin_circuit_breaker_service import admin_list_circuit_breakers
from app.services.circuit_breaker import FAILED_TASK_RETRY_DELAYS_SECONDS, describe_failed_task_run
from tests.scheduler.test_action_runtime_admission import _admin, _agent, _project


@asynccontextmanager
async def _single_session(db):
    yield db


async def _task(db, *, config=None, binding="task_definition", agent_active=True):
    project = await _project(db)
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project.id, is_active=agent_active)
    task = Task(id=str(uuid.uuid4()), project_id=project.id, name="Nightly summary", task_type="agent_run",
                agent_type="diagnosis", owner_id=admin.id, is_active=True,
                config={"agent_definition_id": agent.id} if config is None else config, dispatch_binding=binding)
    db.add(task)
    await db.commit()
    return task


async def _run(db, monkeypatch, task, *, trigger_type="manual", trigger_id=None):
    import app.db as database_module

    calls: list[str] = []
    retries: list[dict] = []

    async def fake_run_agent_for_task(db_, task_, prompt, **kwargs):
        calls.append(prompt)
        return type("S", (), {"id": None})(), {"response": "done"}

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    monkeypatch.setattr(scheduler, "_schedule_failed_task_retry", lambda **kwargs: retries.append(kwargs))
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type=trigger_type,
                                  trigger_id=trigger_id)
    run = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == run.id))).scalar_one()
    await db.refresh(run)
    await db.refresh(entry)
    failures = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_id == task.id))).scalars().all()
    return run, entry, failures, calls, retries


def _assert_refused_terminal(run, entry, failures, calls, retries, code):
    assert calls == [] and retries == [], "no session, no model, no retry scheduled"
    assert (run.status, run.error) == ("error", code)
    [failure] = failures
    assert (failure.status, failure.next_retry_at) == ("admission_refused", None)
    assert failure.last_error == code, "the fixed refusal code is kept, nothing else"
    assert (entry.status, entry.next_retry_at) == ("failed", None)
    decision = run.output["failure_decision"]
    assert decision["reason"] == "execution_admission_refused"
    assert (decision["terminal"], decision["retryable"]) == (True, False)
    assert (decision["retry_delay_seconds"], decision["next_retry_at"], decision["queue_status"]) == (None, None, "failed")
    assert decision["retry_policy"] == {"name": "execution_admission_refusal", "delays_seconds": [],
                                        "max_retry_attempts": 0}
    return failure


@pytest.mark.parametrize(("setup", "code", "refusal_key"), [
    ({"config": {}}, "action_instruction_missing", "action_admission_refusal"),
    ({"config": {"prompt": "Summarize"}, "binding": "agent_definition"}, "dispatch_binding_agent_required",
     "action_admission_refusal"),
    ({"agent_active": False}, None, "agent_definition_refusal"),
])
async def test_each_typed_refusal_family_records_one_terminal_failure_and_no_retry(db, monkeypatch, setup, code,
                                                                                    refusal_key):
    task = await _task(db, **setup)
    run, entry, failures, calls, retries = await _run(db, monkeypatch, task)
    assert refusal_key in run.output
    _assert_refused_terminal(run, entry, failures, calls, retries, code or run.output[refusal_key]["code"])


async def test_a_refused_retry_attempt_ends_its_existing_chain_and_keeps_its_history(db, monkeypatch):
    task = await _task(db, agent_active=False)
    earlier = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="error", trigger_type="manual",
                      started_by=task.owner_id, input_={}, error="scheduled_task_failed")
    db.add(earlier)
    await db.flush()
    chain = FailedTaskRun(task_id=task.id, task_run_id=earlier.id, retry_count=2, status="pending_retry",
                          last_error="scheduled_task_failed")
    db.add(chain)
    await db.commit()

    run, entry, failures, calls, retries = await _run(db, monkeypatch, task, trigger_type="retry", trigger_id=chain.id)
    failure = _assert_refused_terminal(run, entry, failures, calls, retries, run.output["agent_definition_refusal"]["code"])
    assert failure.id == chain.id and failure.retry_count == 3 and failure.task_run_id == run.id
    assert (await db.get(TaskRun, earlier.id)).status == "error", "earlier attempts stay as they were"


async def test_the_same_text_from_an_untyped_exception_keeps_the_ordinary_backoff(db, monkeypatch):
    task = await _task(db)

    async def failing_admission(db_, task_):
        raise RuntimeError("agent_definition_inactive")

    monkeypatch.setattr(task_run_kinds, "admit_agent_turn", failing_admission)
    run, entry, failures, calls, retries = await _run(db, monkeypatch, task)
    [failure] = failures
    assert calls == [] and run.status == "error"
    assert failure.status == "pending_retry" and failure.next_retry_at is not None
    assert entry.status == "retry_pending"
    assert retries == [{"task_id": task.id, "failed_task_run_id": failure.id,
                        "delay_seconds": FAILED_TASK_RETRY_DELAYS_SECONDS[0]}]
    decision = run.output["failure_decision"]
    assert (decision["reason"], decision["retryable"], decision["terminal"]) == ("retry_scheduled", True, False)
    assert decision["retry_policy"]["delays_seconds"] == FAILED_TASK_RETRY_DELAYS_SECONDS


async def test_a_reloaded_refusal_reads_the_same_terminal_decision_in_the_admin_projection(db, monkeypatch):
    task = await _task(db, config={})
    run, *_ = await _run(db, monkeypatch, task)
    row = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_run_id == run.id))).scalar_one()
    await db.refresh(row)
    reloaded = describe_failed_task_run(row).as_dict()
    assert reloaded == {**run.output["failure_decision"], "retry_delay_seconds": None}

    projected = next(item for item in (await admin_list_circuit_breakers(db))["failed_task_runs"] if item["id"] == row.id)
    assert (projected["status"], projected["reason"], projected["queue_status"]) == (
        "admission_refused", "execution_admission_refused", "failed")
    assert (projected["terminal"], projected["retryable"], projected["next_retry_at"]) == (True, False, None)
    assert projected["retry_policy"] == {"name": "execution_admission_refusal", "delays_seconds": [],
                                         "max_retry_attempts": 0}
    assert projected["decision"] == reloaded
