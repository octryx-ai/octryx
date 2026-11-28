"""Contract: an Action explicitly bound to its AgentDefinition runs without a Worker record, within the existing
limits, and is refused when its stored binding changed."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import AgentDefinition, Task, User
from app.models.project.task import TaskStep
from app.services.admin.task import _admin_task_management as admin_tasks
from app.services.admin.task import _admin_task_steps as admin_steps
from app.services.auth.tokens import hash_password
from tests.action_agent_binding_support import BOUND, _task
from tests.scheduler.test_action_runtime_admission import _admin, _agent, _project, _run


async def _bound_payload(db, project, **config):
    admin = await _admin(db)
    agent = await _agent(db, admin.id, project.id)
    await db.commit()
    return agent, {"name": f"bound-{uuid.uuid4().hex[:6]}", "agent_type": "diagnosis", "project_id": project.id,
                   "task_type": "agent_run", "config": {"agent_definition_id": agent.id, **config},
                   "dispatch_binding": BOUND}


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


def _code(exc) -> str:
    assert exc.value.status_code == 422 and exc.value.detail["field"] == "dispatch_binding"
    return exc.value.detail["code"]


async def _mutated(db, project, mutate):
    bound = await _task(db, project, binding=BOUND)
    await mutate(bound)
    await db.commit()
    return bound


async def test_explicit_binding_is_saved_and_read_and_a_missing_one_is_refused(db):
    project = await _project(db)
    agent, payload = await _bound_payload(db, project)
    admin = await _admin(db)
    created = await admin_tasks.create_task(db, user_id=admin.id, payload=payload)
    assert created["dispatch_binding"] == BOUND
    own = await admin_tasks.create_task(db, user_id=admin.id, payload={**payload, "dispatch_binding": "task_definition"})
    assert own["dispatch_binding"] == "task_definition", "a selected agent alone never implies the agent binding"
    before = await _count(db, Task)
    for missing in ({**payload, "dispatch_binding": None},
                    {key: value for key, value in payload.items() if key != "dispatch_binding"}):
        with pytest.raises(HTTPException) as exc:
            await admin_tasks.create_task(db, user_id=admin.id, payload=missing)
        assert _code(exc) == "dispatch_binding_invalid"
    assert await _count(db, Task) == before


@pytest.mark.parametrize(("change", "code"), [
    ({"dispatch_binding": "worker"}, "dispatch_binding_invalid"),
    ({"dispatch_binding": ["agent_definition"]}, "dispatch_binding_invalid"),
    ({"task_type": "custom"}, "dispatch_binding_type_unsupported"),
    ({"task_type": "webhook_relay"}, "dispatch_binding_type_unsupported"),
    ({"config": {"prompt": "Summarize"}}, "dispatch_binding_agent_required"),
    ({"config": {"agent_definition_id": "  "}}, "dispatch_binding_agent_required"),
    ({"config": {"agent_definition_id": str(uuid.uuid4())}}, "action_agent_not_found"),
])
async def test_an_invalid_bound_create_is_refused_with_zero_writes(db, change, code):
    project = await _project(db)
    _agent_row, payload = await _bound_payload(db, project)
    before = await _count(db, Task)
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.create_task(db, user_id=(await _admin(db)).id, payload={**payload, **change})
    assert _code(exc) == code
    assert await _count(db, Task) == before


async def test_foreign_other_workspace_and_inactive_agents_are_refused_at_save(db):
    project, other = await _project(db), await _project(db, "other")
    admin = await _admin(db)
    stranger = User(username=f"s-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:6]}@example.test",
                    password_hash=hash_password("Stranger-Pw-123456"), is_active=True)
    db.add(stranger)
    await db.flush()
    foreign = await _agent(db, stranger.id, project.id)
    elsewhere = await _agent(db, admin.id, other.id)
    inactive = await _agent(db, admin.id, project.id, is_active=False)
    await db.commit()
    _agent_row, payload = await _bound_payload(db, project)
    # Agents are shared in their Workspace, so another member's agent there is bindable; an agent the owner
    # cannot see (here: one that does not exist) is not found, another Workspace's agent is a mismatch.
    await admin_tasks.create_task(db, user_id=admin.id, payload={**payload, "config": {"agent_definition_id": foreign.id}})
    for agent_id, code in [(str(uuid.uuid4()), "action_agent_not_found"), (elsewhere.id, "action_agent_workspace_mismatch")]:
        with pytest.raises(HTTPException) as exc:
            await admin_tasks.create_task(db, user_id=admin.id,
                                          payload={**payload, "config": {"agent_definition_id": agent_id}})
        assert _code(exc) == code
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.create_task(db, user_id=admin.id,
                                      payload={**payload, "config": {"agent_definition_id": inactive.id}})
    assert _code(exc) not in {"dispatch_binding_agent_required", "action_agent_not_found"}


async def test_update_omission_keeps_the_binding_null_is_refused_and_a_dependent_change_is_validated(db):
    project = await _project(db)
    _agent_row, payload = await _bound_payload(db, project)
    task_id = (await admin_tasks.create_task(db, user_id=(await _admin(db)).id, payload=payload))["id"]

    assert (await admin_tasks.update_task(db, task_id=task_id, payload={"name": "renamed"}))["dispatch_binding"] == BOUND
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.update_task(db, task_id=task_id, payload={"name": "not-applied", "config": {"prompt": "x"}})
    assert _code(exc) == "dispatch_binding_agent_required"
    stored = await db.get(Task, task_id)
    await db.refresh(stored)
    assert stored.name == "renamed" and stored.config.get("agent_definition_id")
    with pytest.raises(HTTPException) as exc:
        await admin_tasks.update_task(db, task_id=task_id, payload={"dispatch_binding": None})
    assert _code(exc) == "dispatch_binding_invalid"
    await db.refresh(stored)
    assert stored.dispatch_binding == BOUND


async def test_panel_route_requires_the_binding_on_create_and_keeps_it_on_update(client, auth_headers, db):
    project = await _project(db)
    _agent_row, payload = await _bound_payload(db, project)
    unbound = {key: value for key, value in payload.items() if key != "dispatch_binding"}
    missing = await client.post("/admin/chat/api/panel/tasks", json=unbound, headers=auth_headers)
    assert missing.status_code == 422
    created = await client.post("/admin/chat/api/panel/tasks", json=payload, headers=auth_headers)
    assert created.status_code == 200, created.text
    url = f"/admin/chat/api/panel/tasks/{created.json()['id']}"
    assert (await client.put(url, json={"description": "kept"}, headers=auth_headers)).json()["dispatch_binding"] == BOUND
    refused = await client.put(url, json={"dispatch_binding": "worker"}, headers=auth_headers)
    assert refused.status_code == 422
    assert (await client.put(url, json={"dispatch_binding": None}, headers=auth_headers)).json()["dispatch_binding"] == BOUND


async def test_a_bound_action_never_gains_an_enabled_step(db):
    project = await _project(db)
    _agent_row, payload = await _bound_payload(db, project)
    task_id = (await admin_tasks.create_task(db, user_id=(await _admin(db)).id, payload=payload))["id"]
    with pytest.raises(HTTPException) as exc:
        await admin_steps.create_task_step(db, task_id=task_id, payload={"name": "Pipeline"})
    assert _code(exc) == "dispatch_binding_steps_enabled"
    assert not (await db.execute(select(TaskStep.id).where(TaskStep.task_id == task_id))).first()
    disabled = await admin_steps.create_task_step(db, task_id=task_id, payload={"name": "Draft", "is_enabled": False})
    with pytest.raises(HTTPException) as exc:
        await admin_steps.update_task_step(db, task_id=task_id, step_id=disabled["id"], payload={"is_enabled": True})
    assert _code(exc) == "dispatch_binding_steps_enabled"
    step = await db.get(TaskStep, disabled["id"])
    await db.refresh(step)
    assert step.is_enabled is False


async def test_a_valid_bound_action_runs_its_selected_agent(db, monkeypatch):
    project = await _project(db)
    bound = await _task(db, project, binding=BOUND)
    run, entry, calls = await _run(db, monkeypatch, bound)
    assert run.status == "success" and entry.status == "completed"
    assert len(calls) == 1 and calls[0]["agent_definition"]["id"] == bound.config["agent_definition_id"]


@pytest.mark.parametrize(("mutation", "code"), [
    ("type", "dispatch_binding_type_unsupported"),
    ("steps", "dispatch_binding_steps_enabled"),
    ("agent_removed", "dispatch_binding_agent_required"),
    ("agent_missing", "action_agent_not_found"),
])
async def test_a_bound_action_changed_after_save_is_refused_before_any_routing(db, monkeypatch, mutation, code):
    from app.scheduler.execution import step_executor

    project = await _project(db)

    async def mutate(task):
        if mutation == "type":
            task.task_type = "webhook_relay"
        elif mutation == "steps":
            db.add(TaskStep(task_id=task.id, position=1, name="Relay", step_type="analysis", is_enabled=True))
        elif mutation == "agent_removed":
            task.config = {"prompt": "Run without the agent"}
        else:
            task.config = {"agent_definition_id": str(uuid.uuid4())}

    bound = await _mutated(db, project, mutate)
    pipeline: list[str] = []

    async def fake_step_execute(self, db_, task_, task_run_):
        pipeline.append(task_.id)
        return {"steps": {}}

    monkeypatch.setattr(step_executor.StepExecutor, "execute", fake_step_execute)
    run, entry, calls = await _run(db, monkeypatch, bound)
    assert calls == [] and pipeline == [], "no agent turn, no step pipeline, no other task type"
    assert (run.status, run.error) == ("error", code)
    assert run.output["action_admission_refusal"]["code"] == code
    assert entry.completed_at is not None and entry.status != "pending", "the queue lifecycle completes"


async def test_an_inactive_selected_agent_keeps_its_typed_refusal_on_a_bound_action(db, monkeypatch):
    project = await _project(db)
    bound = await _task(db, project, binding=BOUND)
    agent = await db.get(AgentDefinition, bound.config["agent_definition_id"])
    agent.is_active = False
    await db.commit()
    run, _entry_row, calls = await _run(db, monkeypatch, bound)
    assert calls == [] and run.status == "error" and "agent_definition_refusal" in run.output
