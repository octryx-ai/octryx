from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project
from app.services.admin.project import admin_project_config_service


@pytest.mark.asyncio
async def test_merge_project_config_preserves_existing_nested_values(db, auth_user):
    project = Project(
        id=str(uuid.uuid4()),
        name=f"project-config-merge-{uuid.uuid4()}",
        config={"tts": {"enabled": True, "default_voice": "nova"}},
    )
    db.add(project)
    await db.commit()

    payload = await admin_project_config_service.merge_project_config(
        db,
        project_id=project.id,
        patch={"tts": {"default_speed": 1.2}, "stt": {"enabled": True}},
        actor_user_id=auth_user.id,
    )

    assert payload["config"]["tts"] == {
        "enabled": True,
        "default_voice": "nova",
        "default_speed": 1.2,
    }
    assert payload["config"]["stt"] == {"enabled": True}


@pytest.mark.asyncio
async def test_merge_project_config_normalizes_policy_sensitive_keys(db, auth_user):
    project = Project(
        id=str(uuid.uuid4()),
        name=f"project-config-policy-{uuid.uuid4()}",
        config={},
    )
    db.add(project)
    await db.commit()

    payload = await admin_project_config_service.merge_project_config(
        db,
        project_id=project.id,
        patch={
            "runtime_policy": {
                "default_bundle": {
                    "execution_runtime_sandbox_mode": "hard",
                    "execution_runtime_docker_network_mode": "host",
                    "execution_runtime_docker_memory_mb": "99999",
                },
            },
            "tool_policy": {
                "allowlist": "bash",
                "denylist": ["run_cli_command"],
                "mode": "read_only",
                "allow_write_tools": False,
            },
            "repository_bootstrap": {
                "enabled": True,
                "provider": "GitHub",
                "workspace_subdir": " workspace ",
            },
        },
        actor_user_id=auth_user.id,
    )

    runtime_policy = payload["config"]["runtime_policy"]
    assert runtime_policy["default_bundle"]["execution_runtime_sandbox_mode"] == "hard"
    assert runtime_policy["default_bundle"]["execution_runtime_docker_network_mode"] == "bridge"
    assert runtime_policy["default_bundle"]["execution_runtime_docker_memory_mb"] == 8192
    assert runtime_policy["default_bundle"]["execution_runtime_allow_host_fallback"] is False
    assert "tool_policy" not in runtime_policy

    tool_policy = payload["config"]["tool_policy"]
    assert tool_policy["allowlist"] == []
    assert tool_policy["denylist"] == ["run_cli_command"]
    assert tool_policy["mode"] == "read_only"
    assert tool_policy["allow_write_tools"] is False

    bootstrap = payload["config"]["repository_bootstrap"]
    assert bootstrap["provider"] == "github"
    assert bootstrap["workspace_subdir"] == "workspace"

    audit_log = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == project.id,
                AuditLog.action == "admin.project_config.updated",
            )
        )
    ).scalar_one()
    assert audit_log.user_id == auth_user.id
    assert audit_log.resource_type == "project_config"
    assert audit_log.details["project_id"] == project.id
    assert audit_log.details["changed_keys"] == ["repository_bootstrap", "runtime_policy", "tool_policy"]
    assert audit_log.details["after"]["tool_policy"]["denylist"] == ["run_cli_command"]


