"""Agent task outcomes: coding delivery tasks block until clarified."""

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, AgentStep, Project, Task, TaskRun, WorkItem
from app.scheduler import TaskScheduler


@pytest.mark.asyncio
async def test_coding_delivery_agent_task_creates_work_item_and_blocks_until_clarified(db, monkeypatch, auth_user):
    import app.db as database_module

    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=auth_user.id,
        project_id=project.id,
        name="Coding Delivery Agent",
        # A3: the explicit execution mode, not the name, gives the run its work-item envelope.
        execution_mode="coding_delivery",
        description="Runtime-gated coding delivery",
        goal="Deliver coding work through Agent Task gates",
        agent_type="change",
        thinking_level="deep",
        branch_prefix="octryx",
        require_self_review=True,
        system_prompt="Use internal Agent Task state.",
        output_prompt="Return delivery status.",
        is_active=True,
    )
    db.add(agent)
    await db.flush()
    step = AgentStep(
        id=str(uuid.uuid4()),
        agent_id=agent.id,
        position=1,
        name="Implement and verify",
        step_type="change",
        instructions="Implement after clarification.",
        success_criteria="Verified.",
        is_enabled=True,
    )
    step.allowed_tools = ["edit_workspace_file"]
    db.add(step)
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="Fix unclear production bug",
        description="Created from Jira/webhook fallback.",
        task_type="agent_run",
        agent_type="change",
        owner_id=auth_user.id,
        is_active=True,
        config={
            "agent_definition_id": agent.id,
            "prompt": "Fix the bug. It should work.",
        },
    )
    db.add(task)
    await db.commit()

    observed_metadata: dict = {}

    async def fake_run_agent_for_task(db, task, prompt, **kwargs):
        observed_metadata.update(kwargs["session_metadata"])

        class DummySession:
            id = "coding-session-123"

        return DummySession(), {"response": "blocked for clarification"}

    @asynccontextmanager
    async def fake_session_factory():
        yield db

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", fake_session_factory)
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)

    await scheduler._execute_task(task.id, trigger_type="webhook")

    latest_run = (
        await db.execute(
            select(TaskRun).where(TaskRun.task_id == task.id).order_by(TaskRun.started_at.desc()).limit(1)
        )
    ).scalar_one()
    assert latest_run.status == "success"
    assert latest_run.output["coding_run"]["clarification_state"] == "needed"
    assert latest_run.output["coding_run"]["clarification"]["readiness"] == "blocked"
    assert observed_metadata["coding_run_work_item_id"] == latest_run.output["coding_run"]["work_item_id"]
    assert observed_metadata["coding_run"]["clarification_state"] == "needed"

    work_item = await db.get(WorkItem, observed_metadata["coding_run_work_item_id"])
    assert work_item is not None
    assert work_item.source_type == "platform"
    assert work_item.source_id == f"task:{task.id}"
    # The runtime session is linked back onto the work item for handover.
    assert work_item.source_fields_json["coding_run_sessions"][0]["session_id"] == "coding-session-123"
