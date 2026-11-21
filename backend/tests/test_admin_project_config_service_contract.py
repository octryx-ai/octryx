from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.agent.core.prompts.prompt_templates import PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY
from app.models import AuditLog, Project, PromptConfigRevision
from app.services.admin.project import _admin_project_config_owners, admin_project_config_service


def test_project_config_key_owner_inventory_marks_policy_sensitive_keys():
    owners = {
        owner["key"]: owner
        for owner in _admin_project_config_owners.list_project_config_key_owners()
    }

    assert owners["runtime_policy"]["owner"] == "runtime_policy_bundle"
    assert owners["runtime_policy"]["policy_sensitive"] is True
    assert owners["tool_policy"]["policy_sensitive"] is True
    assert owners["repository_bootstrap"]["validation"] == "normalize_repository_bootstrap_config"
    assert owners["tts"]["owner"] == "tts service"
    assert owners["stt"]["owner"] == "stt service"


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


@pytest.mark.asyncio
async def test_merge_project_config_records_prompt_override_revisions(db, auth_user):
    project = Project(
        id=str(uuid.uuid4()),
        name=f"project-config-prompt-{uuid.uuid4()}",
        config={},
    )
    db.add(project)
    await db.commit()

    await admin_project_config_service.merge_project_config(
        db,
        project_id=project.id,
        patch={
            PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY: {
                "variant_routing": {"standard": "minimal", "summary": "admin"},
            }
        },
        actor_user_id=auth_user.id,
    )

    revisions = (
        await db.execute(
            select(PromptConfigRevision)
            .where(PromptConfigRevision.scope_id == project.id)
            .order_by(PromptConfigRevision.config_key.asc())
        )
    ).scalars().all()
    assert len(revisions) == 2
    assert {revision.created_by for revision in revisions} == {auth_user.id}
    assert {
        f"{PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY}.variant_routing.standard",
        f"{PROJECT_SYSTEM_PROMPT_OVERRIDE_CONFIG_KEY}.variant_routing.summary",
    } == {revision.config_key for revision in revisions}
