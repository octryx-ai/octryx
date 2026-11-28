"""Tests for the admin tools page and saved script persistence."""

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project, SavedPythonScript, StoredSecret


@pytest.mark.asyncio
async def test_admin_tools_page_and_save_script(admin_client, db):
    page_resp = await admin_client.get("/admin/tools")
    assert page_resp.status_code == 200
    assert "Built-in Tools" in page_resp.text
    assert "Saved Python Scripts" in page_resp.text
    assert "Test Connection" in page_resp.text

    save_resp = await admin_client.post(
        "/admin/tools/scripts/save",
        data={
            "name": "sum_values_ui",
            "purpose": "Add numbers via UI",
            "description": "Simple reusable script",
            "code": "def main(args):\n    return {'total': args.get('a', 0) + args.get('b', 0)}\n",
            "is_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    script = (await db.execute(select(SavedPythonScript).where(SavedPythonScript.name == "sum_values_ui"))).scalar_one()
    assert script.purpose == "Add numbers via UI"
    assert script.is_active is True


@pytest.mark.asyncio
async def test_admin_tools_can_save_project_tool_config(admin_client, db):
    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    demo_project_id = demo_project.id
    save_resp = await admin_client.post(
        "/admin/tools/configs/save",
        data={
            "tool_name": "kubernetes",
            "project_id": demo_project_id,
            "description": "Use kubectl for demo cluster",
            "config_json": '{"k8s_use_kubectl": true, "k8s_context": "demo-cluster", "k8s_namespace": "default"}',
            "is_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id == demo_project_id,
                BuiltInToolConfig.tool_name == "kubernetes",
            )
        )
    ).scalar_one()
    assert entry.config["k8s_use_kubectl"] is True
    assert entry.config["k8s_context"] == "demo-cluster"


@pytest.mark.asyncio
async def test_admin_tools_encrypts_secret_fields_in_db(admin_client, db):
    save_resp = await admin_client.post(
        "/admin/tools/configs/save",
        data={
            "tool_name": "jira",
            "project_id": "",
            "description": "Jira secure auth",
            "config_json": '{"jira_url": "https://jira.example.com/jira", "jira_auth_mode": "basic", "jira_username": "alice"}',
            "jira_password": "top-secret",
            "is_active": "true",
        },
    )
    assert save_resp.status_code == 303

    await db.rollback()
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id.is_(None),
                BuiltInToolConfig.tool_name == "jira",
            )
        )
    ).scalar_one()
    assert "jira_password" not in entry.config
    assert entry.config["jira_password_secret_ref"]

    secret = await db.get(StoredSecret, entry.config["jira_password_secret_ref"])
    assert secret is not None
    assert secret.encrypted_value != "top-secret"

    page_resp = await admin_client.get("/admin/tools")
    assert page_resp.status_code == 200
    assert "top-secret" not in page_resp.text


@pytest.mark.asyncio
async def test_admin_tools_rejects_invalid_tool_config_shape(admin_client):
    save_resp = await admin_client.post(
        "/admin/tools/configs/save",
        data={
            "tool_name": "bitbucket",
            "project_id": "",
            "description": "Invalid shape",
            "config_json": '{"bitbucket_url":"https://bitbucket.example.com","bitbucket_allowed_repos":[{"project_key":"RIVER"}]}',
            "is_active": "true",
        },
    )

    assert save_resp.status_code == 400
    assert "bitbucket_allowed_repos entries must include repo_slug" in save_resp.text
