"""Tests for tool config validation, project config, k8s tools, and admin channel/agent."""

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    AgentDefinition,
    AgentStep,
    Project,
)
from app.services.project import get_project_config
from app.services.secret import set_secret_value
from app.services.tool_config import upsert_tool_config, validate_tool_config
from app.tools.context import ToolContext
from app.tools.kubernetes_pods import ListFailedPods
from app.tools.registry import TOOL_REGISTRY


@pytest.mark.asyncio
async def test_project_config_merges_tool_config(db):
    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    secret = await set_secret_value(
        db,
        tool_name="jira",
        project_id=demo_project.id,
        field_name="jira_token",
        value="secret",
    )
    await upsert_tool_config(
        db,
        tool_name="jira",
        project_id=demo_project.id,
        config={
            "jira_url": "https://company.atlassian.net",
            "jira_auth_mode": "cloud_api_token",
            "jira_email": "ops@example.com",
            "jira_token_secret_ref": secret.id,
        },
        description="Jira auth for demo",
        is_active=True,
    )
    await db.commit()

    config = await get_project_config(demo_project.id, db)
    assert config["jira_url"] == "https://company.atlassian.net"
    assert config["jira_email"] == "ops@example.com"
    assert config["jira_token"] == "secret"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_global_tool_config_is_available_without_project(db):
    secret = await set_secret_value(
        db,
        tool_name="bitbucket",
        project_id=None,
        field_name="bitbucket_password",
        value="secret",
    )
    await upsert_tool_config(
        db,
        tool_name="bitbucket",
        project_id=None,
        config={
            "bitbucket_url": "https://bitbucket.example.com/bitbucket",
            "bitbucket_auth_mode": "basic",
            "bitbucket_username": "alice",
            "bitbucket_password_secret_ref": secret.id,
            "bitbucket_allowed_repos": [{"project_key": "RIVER", "repo_slug": "service-config", "enabled": True}],
        },
        description="Global Bitbucket access",
        is_active=True,
    )
    await db.commit()

    config = await get_project_config(None, db)
    assert config["bitbucket_url"] == "https://bitbucket.example.com/bitbucket"
    # Bitbucket sits behind the connector credential boundary: the merged
    # project config carries only the secret reference, never the resolved plaintext;
    # the connector resolves it at its own boundary.
    assert config["bitbucket_password_secret_ref"] == secret.id
    assert "bitbucket_password" not in config


def test_validate_tool_config_rejects_unknown_fields():
    with pytest.raises(ValueError, match="Unknown config fields for jira"):
        validate_tool_config(
            "jira",
            {
                "jira_url": "https://jira.example.com",
                "unexpected": True,
            },
        )


def test_validate_tool_config_rejects_invalid_nested_allowlist_shape():
    with pytest.raises(ValueError, match="bitbucket_allowed_repos entries must include repo_slug"):
        validate_tool_config(
            "bitbucket",
            {
                "bitbucket_url": "https://bitbucket.example.com/bitbucket",
                "bitbucket_allowed_repos": [{"project_key": "RIVER"}],
            },
        )


def test_validate_tool_config_rejects_out_of_range_port():
    with pytest.raises(ValueError, match="postgres_port must be between 1 and 65535"):
        validate_tool_config(
            "postgres",
            {
                "postgres_host": "db.internal",
                "postgres_port": 70000,
            },
        )


@pytest.mark.asyncio
async def test_k8s_tools_use_kubectl_when_configured(monkeypatch):
    async def fake_run_kubectl(context, args, timeout_sec=20, namespace=None):
        payload = {
            "items": [
                {
                    "metadata": {"name": "api-1"},
                    "status": {
                        "phase": "Failed",
                        "containerStatuses": [
                            {
                                "name": "api",
                                "restartCount": 3,
                                "state": {"waiting": {"reason": "CrashLoopBackOff", "message": "boom"}},
                            }
                        ],
                    },
                }
            ]
        }
        return 0, json.dumps(payload), ""

    monkeypatch.setattr("app.tools.kubernetes_pods._run_kubectl", fake_run_kubectl)
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={"k8s_use_kubectl": True, "k8s_context": "demo"},
        workspace_root="/srv/octryx",
    )
    result = await ListFailedPods().execute({"namespace": "default"}, context)
    assert result["source"] == "kubectl"
    assert result["failed_count"] == 1


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_create_channel_tool_starts_channel_runtime(db, monkeypatch, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    tool = TOOL_REGISTRY["admin_create_channel"]
    observed = {}

    from app.plugins import plugin_manager

    async def fake_reload_channel(channel_id, plugin_id, config):
        observed["channel_id"] = channel_id
        observed["plugin_id"] = plugin_id
        observed["config"] = dict(config)
        return True

    monkeypatch.setattr(plugin_manager, "reload_channel", fake_reload_channel)
    monkeypatch.setattr(plugin_manager, "get_channel_status", lambda channel_id: "running")

    ctx = ToolContext(
        user_id=auth_user.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session",
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
    )
    result = await tool.execute(
        {
            "plugin_id": "slack",
            "name": "Acme Orders Slack",
            "project_id": project.id,
            "enabled": True,
            "config": {"bot_token": "x", "signing_secret": "y", "default_target": "C123"},
        },
        ctx,
    )

    assert result["status"] == "created"
    assert result["channel"]["status"] == "running"
    assert observed["plugin_id"] == "slack"
    assert observed["config"]["default_target"] == "C123"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_admin_create_agent_tool_can_clone_existing_agent(db, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    base_agent = AgentDefinition(
        id=str(uuid.uuid4()),
        owner_id=auth_user.id,
        project_id=project.id,
        name="Base Knowledge Builder",
        description="Base agent",
        goal="Base goal",
        agent_type="change",
        thinking_level="deep",
        branch_prefix="octryx",
        system_prompt="Base system prompt",
        output_prompt="Base output prompt",
        is_active=True,
    )
    db.add(base_agent)
    await db.flush()
    db.add(
        AgentStep(
            id=str(uuid.uuid4()),
            agent_id=base_agent.id,
            position=1,
            name="Inspect",
            step_type="analysis",
            instructions="Inspect source",
            success_criteria="Done",
            allowed_tools=["list_project_knowledge"],
            is_enabled=True,
        )
    )
    await db.commit()

    tool = TOOL_REGISTRY["admin_create_agent"]
    ctx = ToolContext(
        user_id=auth_user.id,
        project_ids=[project.id],
        roles=["admin"],
        session_id="session",
        project_config={},
        db=db,
        workspace_root=str(Path.cwd()),
    )
    result = await tool.execute(
        {
            "name": "README Knowledge Builder",
            "clone_from_agent_id": base_agent.id,
            "goal": "README-based knowledge sync",
        },
        ctx,
    )

    assert result["status"] == "created"
    assert result["agent"]["clone_source_id"] == base_agent.id
    assert result["agent"]["step_count"] == 1
    created = await db.get(AgentDefinition, result["agent"]["id"])
    assert created is not None
    assert created.system_prompt == "Base system prompt"
