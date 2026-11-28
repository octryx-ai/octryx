"""Entity versions of agent definitions and task steps, and the task dependency panel's CRUD with its cycle guard."""

import uuid

import pytest
from sqlalchemy import select

from app.models import Project
from tests.action_agent_binding_support import bound_action_fields


async def _seed_versioned_task(db):
    from app.models import Task, User
    from app.time_utils import utc_now

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=None,
        name="Versioned task",
        description="for task step rollback",
        task_type="agent_run",
        agent_type="diagnosis",
        # The step below allows ``bash``, which needs ``change``: the task declares it.
        config={"capability_class": "change"},
        owner_id=admin.id,
        created_at=utc_now(),
    )
    db.add(task)
    await db.commit()
    return task


def _rollback_agent_payload(*, description: str, system_prompt: str) -> dict:
    return {
        "name": "Rollback agent",
        "description": description,
        "goal": "Goal",
        "agent_type": "change",
        "thinking_level": "light",
        "system_prompt": system_prompt,
        "output_prompt": "Original output",
        "is_active": True,
    }


async def _create_and_update_agent(client, auth_headers) -> dict:
    create_agent = await client.post(
        "/admin/chat/api/panel/agents",
        json=_rollback_agent_payload(description="Original description", system_prompt="Original prompt"),
        headers=auth_headers,
    )
    assert create_agent.status_code == 200
    agent = create_agent.json()

    update_agent = await client.put(
        f"/admin/chat/api/panel/agents/{agent['id']}",
        json=_rollback_agent_payload(description="Updated description", system_prompt="Updated prompt"),
        headers=auth_headers,
    )
    assert update_agent.status_code == 200
    return agent


async def _assert_agent_generic_rollback_refused(client, auth_headers, agent: dict) -> None:
    agent_versions = await client.get(
        f"/api/v1/entities/agent_definitions/{agent['id']}/versions", headers=auth_headers
    )
    assert agent_versions.status_code == 200
    version_rows = agent_versions.json()
    assert len(version_rows) >= 2

    # Agent definitions keep their generic audit history, but restoring one is
    # owned by the dedicated revision API, so the generic rollback path
    # explicitly refuses and leaves the live row edited.
    rollback_agent = await client.post(
        f"/api/v1/entities/agent_definitions/{agent['id']}/rollback/{version_rows[-1]['version']}",
        headers=auth_headers,
    )
    assert rollback_agent.status_code == 409, rollback_agent.text
    assert rollback_agent.json()["detail"]["code"] == "rollback_owned_by_dedicated_revision_api"

    agent_list = await client.get("/admin/chat/api/panel/agents", headers=auth_headers)
    unchanged_agent = next(row for row in agent_list.json() if row["id"] == agent["id"])
    assert unchanged_agent["description"] == "Updated description"
    assert unchanged_agent["systemPrompt"] == "Updated prompt"


async def _create_and_update_step(client, auth_headers, task) -> dict:
    create_step = await client.post(
        f"/admin/chat/api/panel/tasks/{task.id}/steps",
        json={
            "name": "Original step",
            "step_type": "analysis",
            "instructions": "Original instructions",
            "allowed_tools": ["bash"],
        },
        headers=auth_headers,
    )
    assert create_step.status_code == 200
    step = create_step.json()

    update_step = await client.put(
        f"/admin/chat/api/panel/tasks/{task.id}/steps/{step['id']}",
        json={
            "name": "Updated step",
            "instructions": "Updated instructions",
            "allowed_tools": ["bash", "read_workspace_file"],
        },
        headers=auth_headers,
    )
    assert update_step.status_code == 200
    return step


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_entity_versions_cover_agent_definitions_and_task_steps(client, auth_headers, db):
    task = await _seed_versioned_task(db)

    agent = await _create_and_update_agent(client, auth_headers)

    await _assert_agent_generic_rollback_refused(client, auth_headers, agent)

    step = await _create_and_update_step(client, auth_headers, task)

    step_versions = await client.get(f"/api/v1/entities/task_steps/{step['id']}/versions", headers=auth_headers)
    assert step_versions.status_code == 200
    step_rows = step_versions.json()
    assert len(step_rows) >= 2

    rollback_step = await client.post(
        f"/api/v1/entities/task_steps/{step['id']}/rollback/{step_rows[-1]['version']}",
        headers=auth_headers,
    )
    assert rollback_step.status_code == 200

    steps_list = await client.get(f"/admin/chat/api/panel/tasks/{task.id}/steps", headers=auth_headers)
    restored_step = next(row for row in steps_list.json() if row["id"] == step["id"])
    assert restored_step["name"] == "Original step"
    assert restored_step["instructions"] == "Original instructions"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_task_dependency_panel_crud_and_cycle_guard(client, auth_headers, db):
    project_id = (await db.execute(select(Project).limit(1))).scalar_one().id
    create_a = await client.post(
        "/admin/chat/api/panel/tasks",
        json={"name": "Dependency A", "description": "", "task_type": "agent_run", "agent_type": "diagnosis",
              "project_id": project_id, **await bound_action_fields(db, project_id)},
        headers=auth_headers,
    )
    create_b = await client.post(
        "/admin/chat/api/panel/tasks",
        json={"name": "Dependency B", "description": "", "task_type": "agent_run", "agent_type": "diagnosis",
              "project_id": project_id, **await bound_action_fields(db, project_id)},
        headers=auth_headers,
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200
    task_a = create_a.json()
    task_b = create_b.json()

    upsert = await client.post(
        f"/admin/chat/api/panel/tasks/{task_b['id']}/dependencies",
        json={"depends_on_task_id": task_a["id"], "condition": "success"},
        headers=auth_headers,
    )
    assert upsert.status_code == 200
    payload = upsert.json()
    assert payload["dependencies"][0]["depends_on_task_id"] == task_a["id"]

    cycle = await client.post(
        f"/admin/chat/api/panel/tasks/{task_a['id']}/dependencies",
        json={"depends_on_task_id": task_b["id"], "condition": "success"},
        headers=auth_headers,
    )
    assert cycle.status_code == 400
    assert cycle.json()["error"] == "Task dependency would create a cycle"

    listed = await client.get(f"/admin/chat/api/panel/tasks/{task_b['id']}/dependencies", headers=auth_headers)
    assert listed.status_code == 200
    dependency_id = listed.json()["dependencies"][0]["id"]

    deleted = await client.delete(
        f"/admin/chat/api/panel/tasks/{task_b['id']}/dependencies/{dependency_id}",
        headers=auth_headers,
    )
    assert deleted.status_code == 200
