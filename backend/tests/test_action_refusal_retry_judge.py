"""Independent live-regression guard: permanent admission refusals must not schedule retry storms."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import FailedTaskRun
from app.scheduler import TaskScheduler
from app.services.admin.provider.admin_circuit_breaker_service import _serialize_failed_task_run
from tests.test_action_runtime_admission import _admin, _agent, _project, _run, _task


@pytest.mark.parametrize("refusal", ["inactive_agent", "missing_binding_agent"])
async def test_admission_refusal_ends_once_and_read_model_keeps_reason(db, monkeypatch, refusal):
    project = await _project(db, "no-retry-judge")
    owner = await _admin(db)
    agent = await _agent(db, owner.id, project.id)
    task = await _task(db, project.id, config={"agent_definition_id": agent.id, "prompt": "2, 3"})
    task.dispatch_binding = "agent_definition"
    if refusal == "inactive_agent":
        agent.is_active = False
    else:
        task.config = {"prompt": "2, 3"}
    await db.commit()
    scheduled = []
    monkeypatch.setattr(TaskScheduler, "_schedule_failed_task_retry", lambda self, **kwargs: scheduled.append(kwargs))
    run, queue, calls = await _run(db, monkeypatch, task)
    assert scheduled == [], "a configuration refusal must not create automatic retry runs"
    assert calls == [] and run.session_id is None
    assert run.status == "error" and queue.completed_at is not None
    assert queue.next_retry_at is None
    failure = (await db.execute(select(FailedTaskRun).where(FailedTaskRun.task_run_id == run.id))).scalar_one()
    await db.refresh(failure)
    read_model = _serialize_failed_task_run(failure)
    assert read_model["terminal"] is True and read_model["retryable"] is False
    assert read_model["reason"] == "execution_admission_refused"
    assert read_model["next_retry_at"] is None
    assert read_model["retry_policy"]["delays_seconds"] == []
