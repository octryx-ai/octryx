"""Contract: an Action's general agent turn is admitted before any session or model dispatch."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select

from app.models import AgentDefinition, Project, Task, TaskQueueEntry, TaskRun, User
from app.scheduler import TaskScheduler
from app.scheduler.execution.action_admission import admit_agent_turn, has_authored_instruction
from app.services.admin.task._admin_task_serialization import serialize_task
from app.services.auth.tokens import hash_password
from tests.factories import make_project


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _project(db, label="action") -> Project:
    return await make_project(db, name=f"{label}-{uuid.uuid4().hex[:8]}")


async def _agent(db, owner_id, project_id, **fields) -> AgentDefinition:
    values = {"goal": "Summarize open incidents", "system_prompt": "", "output_prompt": "", "is_active": True}
    values.update(fields)
    agent = AgentDefinition(id=str(uuid.uuid4()), owner_id=owner_id, project_id=project_id,
                            name=f"agent-{uuid.uuid4().hex[:6]}", description="An agent description",
                            agent_type="diagnosis", thinking_level="light", branch_prefix="octryx", **values)
    agent.skill_preferences = {}
    db.add(agent)
    await db.flush()
    return agent


async def _task(db, project_id, *, task_type="agent_run", config=None) -> Task:
    admin = await _admin(db)
    task = Task(dispatch_binding="task_definition", id=str(uuid.uuid4()), project_id=project_id, name="Nightly incident summary", description="",
                task_type=task_type, agent_type="diagnosis", owner_id=admin.id, is_active=True,
                config={} if config is None else config)
    db.add(task)
    await db.commit()
    return task


@asynccontextmanager
async def _single_session(db):
    yield db


async def _run(db, monkeypatch, task, *, after_enqueue=None):
    import app.db as database_module

    calls: list[dict] = []

    async def fake_run_agent_for_task(db_, task_, prompt, **kwargs):
        calls.append({"prompt": prompt, "agent_definition": kwargs.get("agent_definition")})
        return type("S", (), {"id": None})(), {"response": "done"}

    scheduler = TaskScheduler()
    monkeypatch.setattr(database_module, "async_session_factory", lambda: _single_session(db))
    monkeypatch.setattr(scheduler, "_run_agent_for_task", fake_run_agent_for_task)
    payload = await scheduler.run_task_now(task.id, started_by=task.owner_id)
    if after_enqueue is not None:
        await after_enqueue()
    await scheduler._execute_task(task.id, task_run_id=payload["task_run_id"], trigger_type="manual")
    run = (await db.execute(select(TaskRun).where(TaskRun.id == payload["task_run_id"]))).scalar_one()
    entry = (await db.execute(select(TaskQueueEntry).where(TaskQueueEntry.task_run_id == run.id))).scalar_one()
    return run, entry, calls


def _refused(run, entry, calls, code):
    assert calls == [], "no session and no model dispatch"
    assert (run.status, run.error) == ("error", code)
    assert run.output["task_error"] == code
    assert run.output["action_admission_refusal"]["code"] == code
    assert run.completed_at is not None and entry.completed_at is not None
    assert entry.status != "pending", "the queue lifecycle completes"


@pytest.mark.parametrize(
    ("task_type", "config", "code"),
    [
        ("webhook_relay", {"prompt": "relay it"}, "action_type_unsupported"),
        ("diagnosis", {"prompt": "do it"}, "action_type_unsupported"),
        ("agent_run", {"prompt": ["do", "it"]}, "action_prompt_invalid"),
        ("agent_run", {"prompt": {"text": "do it"}}, "action_prompt_invalid"),
        ("agent_run", {"agent_definition_id": {"id": "x"}, "prompt": "do it"}, "action_agent_id_invalid"),
        ("agent_run", {}, "action_instruction_missing"),
        ("agent_run", {"prompt": "   "}, "action_instruction_missing"),
    ],
)
async def test_type_values_and_missing_instruction_are_refused_before_dispatch(db, monkeypatch, task_type, config, code):
    project = await _project(db)
    task = await _task(db, project.id, task_type=task_type, config=config)
    run, entry, calls = await _run(db, monkeypatch, task)
    _refused(run, entry, calls, code)
    assert "Execute scheduled task" not in json.dumps(run.output), "no invented instruction"


async def test_a_non_object_config_is_refused(db):
    # A non-object config cannot even be queued (the existing enqueue reads it as a mapping), so this
    # is checked at the admission boundary itself. Downstream, channel delivery also assumes a mapping
    # (output/channel_output.py:89); that file is outside this admission boundary.
    from types import SimpleNamespace

    from app.scheduler.execution.action_admission import ActionAdmissionError, admit_agent_turn

    task = SimpleNamespace(task_type="agent_run", config=["not", "an", "object"], owner_id="o", project_id="p")
    with pytest.raises(ActionAdmissionError) as refused:
        await admit_agent_turn(db, task)
    assert refused.value.code == "action_config_invalid"


async def test_an_agent_the_owner_cannot_resolve_never_degrades_to_a_plain_turn(db, monkeypatch):
    project = await _project(db)
    missing = await _task(db, project.id, config={"agent_definition_id": str(uuid.uuid4()), "prompt": "do it"})
    _refused(*await _run(db, monkeypatch, missing), "action_agent_not_found")

    stranger = User(username=f"other-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@example.test",
                    password_hash=hash_password("Other-Owner-Pw-123"), is_active=True)
    db.add(stranger)
    await db.flush()
    # An agent is shared in its Workspace, so another member's agent there is the one the
    # Action runs (the owner can resolve it); "cannot resolve" covers a missing or invisible agent only.
    shared_agent = await _agent(db, stranger.id, project.id)
    shared = await _task(db, project.id, config={"agent_definition_id": shared_agent.id, "prompt": "do it"})
    _run_result, _entry, calls = await _run(db, monkeypatch, shared)
    assert [call["agent_definition"]["id"] for call in calls] == [shared_agent.id]


async def test_an_agent_of_another_workspace_is_refused_without_naming_it(db, monkeypatch):
    own, other = await _project(db, "own"), await _project(db, "other")
    admin = await _admin(db)
    agent = await _agent(db, admin.id, other.id)
    task = await _task(db, own.id, config={"agent_definition_id": agent.id, "prompt": "do it"})
    run, entry, calls = await _run(db, monkeypatch, task)
    _refused(run, entry, calls, "action_agent_workspace_mismatch")
    assert other.id not in json.dumps(run.output) and other.id not in (run.error or "")


async def test_an_inactive_agent_keeps_its_existing_typed_refusal(db, monkeypatch):
    project = await _project(db)
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project.id, is_active=False)
    task = await _task(db, project.id, config={"agent_definition_id": agent.id, "prompt": "do it"})
    run, _entry, calls = await _run(db, monkeypatch, task)
    assert calls == [] and run.status == "error"
    assert "agent_definition_refusal" in run.output and "action_admission_refusal" not in run.output


async def test_boilerplate_alone_is_not_an_instruction(db, monkeypatch):
    project = await _project(db)
    admin = await _admin(db)
    empty = await _agent(db, admin.id, project.id, goal="", system_prompt="", output_prompt="")
    task = await _task(db, project.id, config={"agent_definition_id": empty.id})
    _refused(*await _run(db, monkeypatch, task), "action_instruction_missing")
    assert has_authored_instruction({"goal": "", "systemPrompt": " ", "outputPrompt": "",
                                     "steps": [{"isEnabled": False, "instructions": "x"}]}) is False
    assert has_authored_instruction({"steps": [{"isEnabled": True, "instructions": "Check alerts"}]}) is True


@pytest.mark.parametrize("workspace", ["same", "global"])
async def test_owner_visible_same_workspace_or_global_agent_runs_with_its_authored_instruction(db, monkeypatch, workspace):
    project = await _project(db)
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project.id if workspace == "same" else None)
    task = await _task(db, project.id, config={"agent_definition_id": agent.id})
    run, entry, calls = await _run(db, monkeypatch, task)
    assert run.status == "success" and entry.status == "completed"
    assert len(calls) == 1 and calls[0]["agent_definition"]["id"] == agent.id
    assert "Summarize open incidents" in calls[0]["prompt"]


async def test_an_explicit_prompt_runs_unchanged(db, monkeypatch):
    project = await _project(db)
    task = await _task(db, project.id, config={"prompt": "Summarize yesterday's incidents"})
    run, entry, calls = await _run(db, monkeypatch, task)
    assert run.status == "success" and entry.status == "completed"
    assert calls == [{"prompt": "Summarize yesterday's incidents", "agent_definition": None}]


async def test_the_enabled_step_branch_is_unchanged(db, monkeypatch):
    from app.models.project.task import TaskStep
    from app.scheduler.execution import step_executor

    project = await _project(db)
    stepped = await _task(db, project.id, task_type="webhook_relay", config={})
    db.add(TaskStep(task_id=stepped.id, position=1, name="Relay", step_type="analysis", is_enabled=True))
    await db.commit()
    executed: list[str] = []

    async def fake_execute(self, db_, task_, task_run_):
        executed.append(task_.id)
        return {"steps": {}}

    monkeypatch.setattr(step_executor.StepExecutor, "execute", fake_execute)
    run, _entry, calls = await _run(db, monkeypatch, stepped)
    assert executed == [stepped.id] and calls == [] and run.status == "success", "enabled steps take precedence"


async def test_admin_task_serialization_adds_project_id(db):
    project = await _project(db)
    task = await _task(db, project.id, config={"prompt": "x"})
    payload = serialize_task(task, run_count=0, running_count=0, queued_count=0, last_run=None, step_count=0,
                             dependency_count=0, dependent_count=0, next_queue_priority=None)
    assert payload["project_id"] == project.id
    assert {"id", "name", "task_type", "config", "owner_id", "schedule", "is_active"} <= set(payload)


@pytest.mark.asyncio
async def test_rest_action_created_without_task_type_is_admitted(client, auth_headers, db):
    project = await _project(db, "default-type")
    await db.commit()

    created = await client.post("/api/v1/tasks", headers=auth_headers, json={
        "project_id": project.id, "name": "Daily summary", "config": {"prompt": "Summarize open incidents"},
        "dispatch_binding": "task_definition"})

    assert created.status_code == 200, created.text
    task = await db.get(Task, created.json()["id"])
    admitted = await admit_agent_turn(db, task)
    assert admitted.prompt == "Summarize open incidents"
