from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AgentDefinition,
    CapabilityType,
    ControlPlaneRuntimeTarget,
    Project,
    WorkspaceCapabilityBinding,
    WorkspacePolicy,
)
from app.services.workspace_composition import seed_workspace_bundle_foundation


async def _seed_project(db, name):
    project = Project(
        id=str(uuid.uuid4()),
        name=name,
        config={
            "project_agent_preferences": {},
        },
        is_active=True,
    )
    db.add(project)
    await db.flush()
    return project


def _documentation_agent(admin, project, name, description, **extra):
    return AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        name=name,
        description=description,
        agent_type="documentation",
        is_active=True,
        **extra,
    )


async def _load_bindings(db, project_id):
    return list(
        (
            await db.execute(
                select(WorkspaceCapabilityBinding).where(WorkspaceCapabilityBinding.workspace_id == project_id)
            )
        )
        .scalars()
        .all()
    )


async def _seed_bundle_workspace(db, admin, runtime_target):
    project = await _seed_project(db, "workspace-seed-project")

    primary_agent = _documentation_agent(
        admin,
        project,
        "Documentation Agent",
        "Document things.",
        runtime_target_id=runtime_target.id,
        thinking_level="deep",
    )
    hidden_agent = _documentation_agent(admin, project, "Hidden Documentation Agent", "Should stay hidden.")
    db.add_all([primary_agent, hidden_agent])

    project.config = {
        "project_agent_preferences": {
            primary_agent.id: {"status": "primary"},
            hidden_agent.id: {"status": "hidden"},
        },
    }
    await db.commit()
    return project, primary_agent, hidden_agent


async def _assert_policy_seeded_and_preferences_kept(db, project_id):
    policy = (await db.execute(select(WorkspacePolicy).where(WorkspacePolicy.workspace_id == project_id))).scalar_one()
    assert policy.workspace_id == project_id
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()
    assert "project_agent_preferences" in (project.config or {})


@pytest.mark.asyncio
async def test_seed_workspace_bundle_foundation_creates_policy_and_bindings(db, auth_user):
    runtime_target = (await db.execute(select(ControlPlaneRuntimeTarget))).scalars().first()
    assert runtime_target is not None

    project, primary_agent, hidden_agent = await _seed_bundle_workspace(db, auth_user, runtime_target)

    summary = await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    await db.commit()

    assert summary["workspaceId"] == project.id
    await _assert_policy_seeded_and_preferences_kept(db, project.id)

    bindings = await _load_bindings(db, project.id)
    binding_by_key = {binding.binding_key: binding for binding in bindings}

    primary_binding = binding_by_key[f"agent-definition:{primary_agent.id}"]
    assert primary_binding.is_default is True
    assert primary_binding.binding_status == "active"
    assert primary_binding.is_enabled is True

    hidden_binding = binding_by_key[f"agent-definition:{hidden_agent.id}"]
    assert hidden_binding.binding_status == "hidden"
    assert hidden_binding.is_enabled is False

    runtime_bindings = [binding for binding in bindings if binding.capability_kind == "runtime"]
    assert len(runtime_bindings) == 1
    assert runtime_bindings[0].source_entity_id == runtime_target.id

    capability_types = list((await db.execute(select(CapabilityType))).scalars().all())
    assert any(item.kind == "agent" for item in capability_types)
    assert any(item.kind == "runtime" for item in capability_types)

    rerun_summary = await seed_workspace_bundle_foundation(db, workspace_id=project.id)
    await db.commit()
    assert rerun_summary["workspaceId"] == project.id
    rerun_bindings = await _load_bindings(db, project.id)
    rerun_binding_by_key = {binding.binding_key: binding for binding in rerun_bindings}
    assert rerun_binding_by_key[f"agent-definition:{primary_agent.id}"].is_default is True
    assert rerun_binding_by_key[f"agent-definition:{hidden_agent.id}"].binding_status == "hidden"
