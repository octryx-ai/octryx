"""Shared helpers for the test_workspace_composition_admin_api_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import (
    AgentDefinition,
    ControlPlaneConfig,
    ControlPlaneRuntimeTarget,
    LLMProvider,
    Project,
    User,
)
from tests.conftest import ADMIN_PASSWORD


async def _login_admin(client) -> None:
    resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 303


async def _create_workspace_fixture(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(
        id=str(uuid.uuid4()),
        name=f"workspace-{uuid.uuid4().hex[:8]}",
        config={},
        is_active=True,
    )
    provider = LLMProvider(
        id=str(uuid.uuid4()),
        name=f"provider-{uuid.uuid4().hex[:6]}",
        display_name="Workspace Provider",
        provider_family="local",
        driver="ollama",
        runtime_kind="local",
        auth_mode="none",
        is_global=True,
        is_active=True,
    )
    control_plane_config = ControlPlaneConfig(
        id=str(uuid.uuid4()),
        name=f"workspace-config-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    runtime_target = ControlPlaneRuntimeTarget(
        id=str(uuid.uuid4()),
        config_id=control_plane_config.id,
        provider_id=provider.id,
        model_id="gemma4:e4b",
        priority=1,
        is_active=True,
    )
    agent_one = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        runtime_target_id=runtime_target.id,
        name="Workspace Research Agent",
        description="Collect evidence for the workspace.",
        agent_type="diagnosis",
        thinking_level="light",
        is_active=True,
    )
    agent_two = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=admin.id,
        project_id=project.id,
        runtime_target_id=runtime_target.id,
        name="Workspace Delivery Agent",
        description="Deliver workspace output.",
        agent_type="change",
        thinking_level="deep",
        is_active=True,
    )
    project.config = {
        "project_agent_preferences": {agent_one.id: {"status": "primary"}},
    }
    db.add_all(
        [
            project,
            provider,
            control_plane_config,
            runtime_target,
            agent_one,
            agent_two,
        ]
    )
    await db.commit()
    return {
        "project": project,
        "runtime_target": runtime_target,
        "agents": [agent_one, agent_two],
    }
