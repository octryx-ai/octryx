"""Independent judge regressions: a stored binding must not change execution kind."""
from __future__ import annotations

import pytest

from app.models import TaskStep
from tests.test_action_runtime_admission import _admin, _agent, _project, _run, _task


@pytest.mark.parametrize("mutation", ["remove_agent", "other_type", "enabled_step"])
async def test_bound_action_refuses_later_incompatible_changes(db, monkeypatch, mutation):
    project = await _project(db, "binding-judge")
    owner = await _admin(db)
    agent = await _agent(db, owner.id, project.id)
    task = await _task(db, project.id, config={"agent_definition_id": agent.id, "prompt": "Sum 2 and 3"})
    task.dispatch_binding = "agent_definition"
    if mutation == "remove_agent":
        task.config = {"prompt": "Sum 2 and 3"}
    elif mutation == "other_type":
        task.task_type = "custom"
    else:
        db.add(TaskStep(task_id=task.id, position=1, name="Unexpected pipeline", step_type="output", is_enabled=True))
    await db.commit()
    run, queue, calls = await _run(db, monkeypatch, task)
    assert calls == [], "the bound agent must never degrade to an agent-less or other execution path"
    assert run.status == "error"
    assert run.session_id is None, "refuse before creating a pipeline or agent session"
    assert str(run.error).startswith("dispatch_binding_")
    assert queue.completed_at is not None
    assert queue.status != "pending"
