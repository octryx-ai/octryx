"""Cancelling a task run cancels its whole session tree, whoever owns the sessions."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app import runtime_lifecycle
from app.models import Session, TaskRun
from app.services.admin.task._admin_task_management import cancel_task_run
from tests.action_agent_binding_support import _task
from tests.test_action_runtime_admission import _project


def _session(owner_id: str, *, parent_id: str | None = None, status: str = "active") -> Session:
    return Session(id=str(uuid.uuid4()), user_id=owner_id, agent_type="diagnosis", status=status,
                   parent_session_id=parent_id, metadata_={})


async def test_cancelling_a_run_cancels_its_session_tree_and_keeps_archived_sessions(db, monkeypatch):
    project = await _project(db)
    task = await _task(db, project, binding="task_definition")
    root = _session(task.owner_id)
    child = _session(task.owner_id, parent_id=root.id)
    grandchild = _session(str(uuid.uuid4()), parent_id=child.id)
    archived = _session(task.owner_id, parent_id=root.id, status="archived")
    unrelated = _session(task.owner_id)
    db.add_all([root, child, grandchild, archived, unrelated])
    run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="running", trigger_type="manual",
                  started_by=task.owner_id, input_={}, session_id=root.id)
    db.add(run)
    await db.commit()
    cancelled_tasks: list[str] = []
    monkeypatch.setattr(runtime_lifecycle, "get_task_scheduler",
                        lambda: SimpleNamespace(cancel_task=cancelled_tasks.append))

    assert await cancel_task_run(db, task_id=task.id, run_id=run.id) == {"status": "cancelled"}

    for session in (root, child, grandchild, archived, unrelated):
        await db.refresh(session)
    assert [root.status, child.status, grandchild.status] == ["cancelled"] * 3
    assert archived.status == "archived"
    assert unrelated.status == "active"
    assert cancelled_tasks == [task.id]
