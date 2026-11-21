"""Generic EntityVersion rollback must not write Agent Definitions.

The dedicated revision API (`/api/v1/agent-definitions/...`) is the only writer
allowed to restore an Agent Definition: it re-validates the snapshot, authorizes
the target Workspace, and records revision lineage. The generic rollback path has
none of those rules, so for this entity type it is an explicit conflict.

Covered here:
  - the generic rollback endpoint denies `agent_definitions` with the stable
    delegation conflict, leaves the live row untouched, and appends no audit row
  - reading generic versions for `agent_definitions` still works (audit history
    is unchanged; only the restore writer moved)
  - `task_steps` still roll back through the generic path; `skills` are versioned only in the skill catalog
  - the service refuses a delegated type before reading a version row, and the
    inner restore writer refuses it too (defense in depth)
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EntityVersion, Task, User
from app.services.entity_version import (
    ROLLBACK_DELEGATED_CODE,
    ROLLBACK_DELEGATED_STATUS,
    SUPPORTED_ENTITY_TYPES,
    rollback_delegation_for,
    rollback_entity_version,
)
from app.services.entity_version import service as entity_version_service
from app.time_utils import utc_now

DELEGATED_TYPE = "agent_definitions"


async def _admin(db: AsyncSession) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _version_count(db: AsyncSession, entity_type: str, entity_id: str) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(EntityVersion)
                .where(
                    EntityVersion.entity_type == entity_type,
                    EntityVersion.entity_id == entity_id,
                )
            )
        ).scalar_one()
    )


async def _agent_with_two_versions(client, auth_headers) -> dict:
    """Create and then edit a panel agent, so it has snapshot history."""
    created = await client.post(
        "/admin/chat/api/panel/agents",
        json={
            "name": "Delegated rollback agent",
            "description": "Original description",
            "goal": "Goal",
            "agent_type": "change",
            "thinking_level": "light",
            "system_prompt": "Original prompt",
            "output_prompt": "Original output",
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    agent = created.json()
    updated = await client.put(
        f"/admin/chat/api/panel/agents/{agent['id']}",
        json={
            "name": "Delegated rollback agent",
            "description": "Updated description",
            "goal": "Goal",
            "agent_type": "change",
            "thinking_level": "light",
            "system_prompt": "Updated prompt",
            "output_prompt": "Original output",
            "is_active": True,
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    return agent


async def test_generic_rollback_is_denied_for_agent_definitions(client, auth_headers, db: AsyncSession):
    agent = await _agent_with_two_versions(client, auth_headers)

    versions = await client.get(
        f"/api/v1/entities/{DELEGATED_TYPE}/{agent['id']}/versions", headers=auth_headers
    )
    assert versions.status_code == 200, versions.text
    rows = versions.json()
    assert len(rows) >= 2
    versions_before = await _version_count(db, DELEGATED_TYPE, agent["id"])

    denied = await client.post(
        f"/api/v1/entities/{DELEGATED_TYPE}/{agent['id']}/rollback/{rows[-1]['version']}",
        headers=auth_headers,
    )
    assert denied.status_code == ROLLBACK_DELEGATED_STATUS, denied.text
    detail = denied.json()["detail"]
    assert detail["code"] == ROLLBACK_DELEGATED_CODE
    assert detail["entity_type"] == DELEGATED_TYPE
    assert "/api/v1/agent-definitions/revisions/" in detail["dedicated_api"]

    # The live row still carries the edited content: nothing was restored.
    listed = await client.get("/admin/chat/api/panel/agents", headers=auth_headers)
    live = next(row for row in listed.json() if row["id"] == agent["id"])
    assert live["description"] == "Updated description"
    assert live["systemPrompt"] == "Updated prompt"

    # And no "rollback" audit row was appended for the refused request.
    assert await _version_count(db, DELEGATED_TYPE, agent["id"]) == versions_before


async def test_agent_definition_audit_history_is_still_recorded_and_readable(
    client, auth_headers, db: AsyncSession
):
    """Only the restore writer moved; snapshots and listing are unchanged."""
    assert DELEGATED_TYPE in SUPPORTED_ENTITY_TYPES
    agent = await _agent_with_two_versions(client, auth_headers)
    assert await _version_count(db, DELEGATED_TYPE, agent["id"]) >= 2

    versions = await client.get(
        f"/api/v1/entities/{DELEGATED_TYPE}/{agent['id']}/versions", headers=auth_headers
    )
    assert versions.status_code == 200
    operations = [
        row["snapshot"].get("__version_meta__", {}).get("operation") for row in versions.json()
    ]
    assert "create" in operations or "update" in operations
    assert "rollback" not in operations


async def test_skills_are_not_generic_entity_versions(client, auth_headers):
    """Skills are versioned only in the skill catalog."""
    skill_id = str(uuid.uuid4())
    versions = await client.get(f"/api/v1/entities/skills/{skill_id}/versions", headers=auth_headers)
    assert versions.status_code == 400
    rollback = await client.post(f"/api/v1/entities/skills/{skill_id}/rollback/1", headers=auth_headers)
    assert rollback.status_code == 400


async def test_task_steps_still_roll_back_through_the_generic_path(client, auth_headers, db: AsyncSession):
    admin = await _admin(db)
    task = Task(dispatch_binding="task_definition",
        id=str(uuid.uuid4()),
        project_id=None,
        name="Delegation guard task",
        description="task step rollback stays supported",
        task_type="agent_run",
        agent_type="diagnosis",
        owner_id=admin.id,
        created_at=utc_now(),
    )
    db.add(task)
    await db.flush()

    created = await client.post(
        f"/admin/chat/api/panel/tasks/{task.id}/steps",
        json={
            "name": "Original step",
            "step_type": "analysis",
            "instructions": "Original instructions",
            "allowed_tools": ["bash"],
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.text
    step = created.json()
    updated = await client.put(
        f"/admin/chat/api/panel/tasks/{task.id}/steps/{step['id']}",
        json={"name": "Updated step", "instructions": "Updated instructions"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text

    versions = await client.get(f"/api/v1/entities/task_steps/{step['id']}/versions", headers=auth_headers)
    assert versions.status_code == 200
    rollback = await client.post(
        f"/api/v1/entities/task_steps/{step['id']}/rollback/{versions.json()[-1]['version']}",
        headers=auth_headers,
    )
    assert rollback.status_code == 200, rollback.text
    steps = await client.get(f"/admin/chat/api/panel/tasks/{task.id}/steps", headers=auth_headers)
    restored = next(row for row in steps.json() if row["id"] == step["id"])
    assert restored["name"] == "Original step"
    assert restored["instructions"] == "Original instructions"


async def test_service_refuses_a_delegated_type_before_reading_a_version(db: AsyncSession):
    """An unknown id gets the delegation conflict, not 404: nothing is looked up."""
    admin = await _admin(db)
    with pytest.raises(HTTPException) as excinfo:
        await rollback_entity_version(
            db,
            entity_type=DELEGATED_TYPE,
            entity_id=str(uuid.uuid4()),
            version=1,
            current_user=admin,
        )
    assert excinfo.value.status_code == ROLLBACK_DELEGATED_STATUS
    assert excinfo.value.detail["code"] == ROLLBACK_DELEGATED_CODE


async def test_inner_restore_writer_also_refuses_a_delegated_type(db: AsyncSession):
    """Defense in depth: no future caller of the generic writer can reach it."""
    with pytest.raises(HTTPException) as excinfo:
        await entity_version_service._restore_snapshot(
            db,
            entity_type=DELEGATED_TYPE,
            entity_id=str(uuid.uuid4()),
            snapshot={"name": "Injected", "owner_id": "someone"},
        )
    assert excinfo.value.status_code == ROLLBACK_DELEGATED_STATUS

    delegation = rollback_delegation_for(DELEGATED_TYPE)
    assert delegation is not None
    assert delegation.dedicated_api.startswith("POST /api/v1/agent-definitions/revisions/")
    assert rollback_delegation_for("skills") is None
    assert rollback_delegation_for("task_steps") is None
