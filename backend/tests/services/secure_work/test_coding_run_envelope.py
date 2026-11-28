"""Coding-run envelope: platform work item + the confirmed Definition of Ready as its clarification gate (N2)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Project, Task, TaskRun, User, WorkflowRun, WorkItem
from app.services.secure_work.coding_run import (
    ensure_coding_run_work_item,
    is_coding_delivery_agent,
    link_coding_run_session,
)

_CODING_AGENT = {"id": "agent-1", "name": "Any name", "executionMode": "coding_delivery"}


async def _task(db, *, prompt: str) -> tuple[Task, TaskRun, User, Project]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Coding run task",
        description="",
        task_type="agent_run",
        owner_id=admin.id,
        is_active=True,
        config={"prompt": prompt},
    )
    db.add(task)
    await db.flush()
    task_run = TaskRun(id=str(uuid.uuid4()), task_id=task.id, status="running", started_by=admin.id)
    db.add(task_run)
    await db.flush()
    return task, task_run, admin, project


def test_only_the_coding_delivery_agent_is_enveloped():
    assert is_coding_delivery_agent(_CODING_AGENT) is True
    assert is_coding_delivery_agent({"name": "some other agent"}) is False
    assert is_coding_delivery_agent({"name": "Coding Delivery Agent"}) is False


@pytest.mark.asyncio
async def test_envelope_creates_platform_item_and_is_idempotent(db):
    task, task_run, _admin, _project = await _task(db, prompt="Fix the bug. It should work.")
    first = await ensure_coding_run_work_item(
        db, task=task, task_run=task_run, agent_definition=_CODING_AGENT,
        prompt=task.config["prompt"], trigger_type="webhook",
    )
    assert first is not None
    assert first["clarification_state"] == "needed"
    assert first["clarification"]["readiness"] == "blocked"
    assert "jira-intake-triage" in first["clarification"]["questions"][0]["question"]

    item = await db.get(WorkItem, first["work_item_id"])
    assert item.source_type == "platform"
    assert item.source_id == f"task:{task.id}"

    second = await ensure_coding_run_work_item(
        db, task=task, task_run=task_run, agent_definition=_CODING_AGENT,
        prompt=task.config["prompt"], trigger_type="webhook",
    )
    assert second["work_item_id"] == first["work_item_id"]
    assert second["clarification_state"] == "needed"
    db.add(WorkflowRun(work_item_id=first["work_item_id"], workflow_kind="phased", workflow_key="jira-intake-triage",
                       title="Triage", status="completed", outcome="done", requested_by=_admin.id))
    await db.flush()
    ready = await ensure_coding_run_work_item(
        db, task=task, task_run=task_run, agent_definition=_CODING_AGENT,
        prompt=task.config["prompt"], trigger_type="webhook",
    )
    assert (ready["clarification_state"], ready["clarification"]["readiness"]) == ("resolved", "ready")
    all_platform = (
        await db.execute(select(WorkItem).where(WorkItem.source_id == f"task:{task.id}"))
    ).scalars().all()
    assert len(all_platform) == 1

    await link_coding_run_session(
        db, work_item_id=first["work_item_id"], session_id="sess-1", task_run_id=task_run.id
    )
    item = await db.get(WorkItem, first["work_item_id"])
    assert item.source_fields_json["coding_run_sessions"][0]["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_non_coding_agent_gets_no_envelope(db):
    task, task_run, _admin, _project = await _task(db, prompt="anything")
    result = await ensure_coding_run_work_item(
        db, task=task, task_run=task_run, agent_definition={"name": "researcher"},
        prompt="anything", trigger_type="manual",
    )
    assert result is None
