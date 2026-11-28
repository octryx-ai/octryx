"""Background execution (scheduled task, task step, Jira watcher) fails the run in ``published`` mode without a
published revision, instead of silently running a different turn."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Project, Task, TaskRun, User
from app.scheduler import TaskScheduler
from app.services.agent_definition_execution_states import (
    AGENT_DEFINITION_EXECUTION_MODE_KEY,
    EXECUTION_MODE_PUBLISHED,
    EXECUTION_MODE_UNKNOWN,
    NOT_CONFIGURED_ERROR_CODE,
    NOT_PUBLISHED_ERROR_CODE,
    RESOLUTION_METADATA_KEY,
    SOURCE_LIVE_DRAFT_ROW,
    STATUS_NEEDS_CONFIGURATION,
    STATUS_NEEDS_PUBLICATION,
)
from app.services.agent_definition_revision_publish import publish_revision
from app.services.agent_definition_revisions import create_draft_revision
from app.services.system_config.values import set_system_config_value
from tests.agent_definition_revision_fixtures import DEFAULT_STEP_TOOL, make_step


async def _set_mode(db, value: str | None) -> None:
    await set_system_config_value(
        db,
        key=AGENT_DEFINITION_EXECUTION_MODE_KEY,
        value=value,
        description="Agent definition execution mode (test)",
    )
    await db.commit()


async def _agent_task(db, *, name: str) -> tuple[AgentDefinition, Task]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (
        await db.execute(select(Project).where(Project.name == "acme-orders"))
    ).scalar_one()
    agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name=name,
        description="Background execution fixture",
        goal="Run in the background",
        agent_type="diagnosis",
        thinking_level="light",
        branch_prefix="octryx",
        system_prompt="Be precise.",
        output_prompt="Report findings.",
        is_active=True,
    )
    agent.skill_preferences = {}
    db.add(agent)
    await db.flush()
    await make_step(db, agent, position=1, name="Step 1", allowed_tools=[DEFAULT_STEP_TOOL])
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=project.id,
        name=f"{name} task",
        description="",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        is_active=True,
        config={"prompt": "do the work", "agent_definition_id": agent.id},
    )
    db.add(task)
    await db.commit()
    return agent, task


@asynccontextmanager
async def _single_session(db):
    yield db


async def _run_task(db, monkeypatch, task: Task) -> tuple[TaskRun, list[dict | None]]:
    import app.db as database_module

    invoked: list[dict | None] = []

    async def fake_run_agent_for_task(db_, task_, prompt, **kwargs):
        invoked.append(kwargs.get("agent_definition"))
        raise AssertionError("the agent must not be invoked for a refused definition")

    scheduler = TaskScheduler()
    monkeypatch.setattr(
        database_module, "async_session_factory", lambda: _single_session(db)
    )
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    await scheduler._execute_task(
        task.id, task_run_id=payload["task_run_id"], trigger_type="manual"
    )
    task_run = (
        await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))
    ).scalar_one()
    return task_run, invoked


@pytest.mark.asyncio
async def test_published_mode_fails_a_scheduled_run_with_no_published_revision(
    db, monkeypatch
):
    _agent, task = await _agent_task(db, name="Unpublished Background Agent")
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)

    task_run, invoked = await _run_task(db, monkeypatch, task)

    assert invoked == [], "the run must not reach the agent at all"
    assert task_run.status == "error"
    assert task_run.error == NOT_PUBLISHED_ERROR_CODE
    refusal = task_run.output["agent_definition_refusal"]
    assert refusal["code"] == NOT_PUBLISHED_ERROR_CODE
    assert refusal["status"] == STATUS_NEEDS_PUBLICATION
    assert refusal["mode"] == EXECUTION_MODE_PUBLISHED
    assert refusal["definition_id"] == task.config["agent_definition_id"]
    assert "Be precise." not in str(task_run.output)


@pytest.mark.asyncio
async def test_an_unknown_mode_fails_a_scheduled_run_as_needs_configuration(
    db, monkeypatch
):
    _agent, task = await _agent_task(db, name="Misconfigured Background Agent")
    await _set_mode(db, "publish")

    task_run, invoked = await _run_task(db, monkeypatch, task)

    assert invoked == []
    assert task_run.status == "error"
    assert task_run.error == NOT_CONFIGURED_ERROR_CODE
    refusal = task_run.output["agent_definition_refusal"]
    assert refusal["status"] == STATUS_NEEDS_CONFIGURATION
    assert refusal["mode"] == EXECUTION_MODE_UNKNOWN
    # The configured value is admin-authored free text; it is never echoed.
    assert "publish" not in str(refusal)


@pytest.mark.asyncio
async def test_a_published_definition_runs_and_records_its_source(db, monkeypatch):
    import app.db as database_module

    agent, task = await _agent_task(db, name="Published Background Agent")
    revision = await create_draft_revision(db, definition=agent, created_by=task.owner_id)
    await publish_revision(db, revision=revision, published_by=task.owner_id)
    await db.commit()
    await _set_mode(db, EXECUTION_MODE_PUBLISHED)

    captured: list[dict] = []

    async def fake_run_agent_for_task(db_, task_, prompt, **kwargs):
        captured.append(dict(kwargs.get("session_metadata") or {}))
        raise RuntimeError("stop after metadata capture")

    scheduler = TaskScheduler()
    monkeypatch.setattr(
        database_module, "async_session_factory", lambda: _single_session(db)
    )
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    await scheduler._execute_task(
        task.id, task_run_id=payload["task_run_id"], trigger_type="manual"
    )

    assert captured, "the run must have reached the agent"
    recorded = captured[0][RESOLUTION_METADATA_KEY]
    assert recorded["mode"] == EXECUTION_MODE_PUBLISHED
    assert recorded["revision_id"] == revision.id
    assert recorded["revision_number"] == 1


@pytest.mark.asyncio
async def test_draft_mode_keeps_running_and_names_the_live_row(db, monkeypatch):
    import app.db as database_module

    _agent, task = await _agent_task(db, name="Draft Background Agent")

    captured: list[dict] = []

    async def fake_run_agent_for_task(db_, task_, prompt, **kwargs):
        captured.append(dict(kwargs.get("session_metadata") or {}))
        raise RuntimeError("stop after metadata capture")

    scheduler = TaskScheduler()
    monkeypatch.setattr(
        database_module, "async_session_factory", lambda: _single_session(db)
    )
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    await scheduler._execute_task(
        task.id, task_run_id=payload["task_run_id"], trigger_type="manual"
    )

    assert captured
    recorded = captured[0][RESOLUTION_METADATA_KEY]
    assert recorded["source"] == SOURCE_LIVE_DRAFT_ROW
    assert recorded["revision_id"] is None
