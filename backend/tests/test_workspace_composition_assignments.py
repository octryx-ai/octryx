"""Workspace and project assignments through the composition admin API: structured defaults and modes, repository policy, knowledge mounts and skill policy."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, CodeRepository, Project, User
from tests.skill_catalog.support import publish_chat_skill
from tests.workspace_composition_admin_api_support import _create_workspace_fixture, _login_admin


@pytest.mark.asyncio
async def test_workspace_assignment_controls_update_structured_defaults_and_modes(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]

    initial = await client.get(f"/admin/chat/api/panel/projects/{project.id}/workspace-composition")
    assert initial.status_code == 200
    payload = initial.json()
    agent_binding = next(item for item in payload["bindings"] if item["capability_kind"] == "agent")
    runtime_binding = next(
        item
        for item in payload["bindings"]
        if item["capability_kind"] == "runtime" and item["is_enabled"]
    )

    invalid = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/assignment-controls",
        json={"default_runtime_binding_key": agent_binding["binding_key"]},
    )
    assert invalid.status_code == 400
    assert "unknown binding" in invalid.text

    updated = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/workspace-composition/assignment-controls",
        json={
            "agent_assignment_mode": "selected_only",
            "runtime_assignment_mode": "selected_only",
            "default_agent_binding_key": agent_binding["binding_key"],
            "default_runtime_binding_key": runtime_binding["binding_key"],
        },
    )
    assert updated.status_code == 200, updated.text
    updated_payload = updated.json()
    controls = updated_payload["assignment_controls"]
    assert controls["agent_assignment_mode"] == "selected_only"
    assert controls["runtime_assignment_mode"] == "selected_only"
    assert controls["default_agent_binding_key"] == agent_binding["binding_key"]
    assert controls["default_runtime_binding_key"] == runtime_binding["binding_key"]
    assert "fallback_runtime_binding_key" not in controls, "the dead fallback runtime is gone"
    assert updated_payload["policy"]["default_bindings"]["agent"] == agent_binding["binding_key"]
    assert updated_payload["policy"]["default_bindings"]["runtime"] == runtime_binding["binding_key"]
    assert "fallback_runtime_binding_key" not in updated_payload["policy"]["runtime_policy"]


@pytest.mark.asyncio
async def test_project_resource_assignments_update_repository_policy_and_knowledge_mounts(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]
    source_project = Project(
        id=str(uuid.uuid4()),
        name="Shared Knowledge Workspace",
        config={},
        is_active=True,
    )
    repo = CodeRepository(
        id=str(uuid.uuid4()),
        project_id=project.id,
        name="service-api",
        repo_root="/workspace/service-api",
        provider="local",
        default_branch="main",
        index_backend="ripgrep",
        semantic_backend="regex",
        structure_backend="regex",
        graph_backend="disabled",
        config_json={},
        capabilities_json={},
        latest_index_summary={},
        last_index_status="not_indexed",
        is_active=True,
    )
    db.add_all([source_project, repo])
    await db.commit()

    initial = await client.get(f"/admin/chat/api/panel/projects/{project.id}/resources")
    assert initial.status_code == 200, initial.text
    initial_payload = initial.json()
    assert initial_payload["repositories"][0]["operation_policy"]["read"] is True
    assert initial_payload["repositories"][0]["operation_policy"]["write"] is False
    assert any(item["project_id"] == source_project.id for item in initial_payload["available_knowledge_bases"])
    # Knowledge shares are retired with the KnowledgeMap store.
    assert "knowledge_shares" not in initial_payload and "knowledge_share_candidates" not in initial_payload

    invalid = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/resources",
        json={"knowledge_mounts": [{"source_project_id": project.id}]},
    )
    assert invalid.status_code == 400
    assert "same project" in invalid.text

    updated = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/resources",
        json={
            "repository_policies": [
                {
                    "repository_id": repo.id,
                    "operations": {
                        "read": True,
                        "branch": True,
                        "write": False,
                        "pr": True,
                        "index": True,
                        "migration": True,
                    },
                }
            ],
            "knowledge_mounts": [
                {"source_project_id": source_project.id, "mount_label": "Shared architecture"}
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["repositories"][0]["operation_policy"]["branch"] is True
    assert payload["repositories"][0]["operation_policy"]["migration"] is True
    assert payload["knowledge_mounts"] == [
        {
            "source_project_id": source_project.id,
            "mount_label": "Shared architecture",
            "access": "read",
            "source_project_name": source_project.name,
        }
    ]
    assert all(
        item["project_id"] != source_project.id
        for item in payload["available_knowledge_bases"]
    )

    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    audit_actions = {
        row.action
        for row in (
            await db.execute(
                select(AuditLog).where(AuditLog.user_id == admin.id, AuditLog.resource_id == project.id)
            )
        ).scalars()
    }
    assert "knowledge_mounts.updated" in audit_actions


@pytest.mark.asyncio
async def test_project_skill_assignments_api_updates_skill_policy(client, db):
    await _login_admin(client)
    fixture = await _create_workspace_fixture(db)
    project = fixture["project"]
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    skill, _version = await publish_chat_skill(db, "workspace-skill", approver_id=admin.id,
                                               description="Workspace skill summary", allowed_roles=("admin",))
    await db.commit()

    initial = await client.get(f"/admin/chat/api/panel/projects/{project.id}/skills")
    assert initial.status_code == 200, initial.text
    assert initial.json()["policy"]["assignment_mode"] == "all_active"
    assert any(item["id"] == skill.id for item in initial.json()["skills"])

    updated = await client.put(
        f"/admin/chat/api/panel/projects/{project.id}/skills",
        json={"assignment_mode": "selected_only", "selected_skill_ids": [skill.id]},
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["policy"]["assignment_mode"] == "selected_only"
    assert payload["selected_skill_ids"] == [skill.id]
