"""Project connector access: grants control global connector inheritance, the access API saves limits, and configured global connectors are listed dynamically."""

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, Project
from app.services.admin.project.admin_project_connector_access_service import list_project_connector_access
from app.services.project import get_project_config
from app.services.tool_config import upsert_tool_config
from tests.conftest import ADMIN_PASSWORD


@pytest.mark.asyncio
async def test_project_connector_grant_controls_global_connector_inheritance(db):
    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    await upsert_tool_config(
        db,
        tool_name="jira",
        project_id=None,
        config={
            "jira_url": "https://jira.example.com/jira",
            "jira_allowed_projects": ["GLOBAL"],
        },
        is_active=True,
    )
    await db.flush()

    without_grant = await get_project_config(demo_project.id, db)
    assert "jira_url" not in without_grant

    await upsert_tool_config(
        db,
        tool_name="jira",
        project_id=demo_project.id,
        config={},
        is_active=True,
    )
    await db.flush()
    inherited = await get_project_config(demo_project.id, db)
    assert inherited["jira_url"] == "https://jira.example.com/jira"
    assert inherited["jira_allowed_projects"] == ["GLOBAL"]

    await upsert_tool_config(
        db,
        tool_name="jira",
        project_id=demo_project.id,
        config={"jira_allowed_projects": ["LOCAL"]},
        is_active=True,
    )
    await db.flush()
    limited = await get_project_config(demo_project.id, db)
    assert limited["jira_url"] == "https://jira.example.com/jira"
    assert limited["jira_allowed_projects"] == ["LOCAL"]


@pytest.mark.asyncio
async def test_project_connector_access_api_saves_limits(client, db):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    response = await client.put(
        f"/admin/chat/api/panel/projects/{demo_project.id}/connectors/jira",
        json={
            "is_active": True,
            "limits": {"jira_allowed_projects": ["RIVER"]},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    jira = next(item for item in payload["connectors"] if item["connector_name"] == "jira")
    assert jira["project_enabled"] is True
    assert jira["project_limits"] == {"jira_allowed_projects": ["RIVER"]}

    await db.rollback()
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id == demo_project.id,
                BuiltInToolConfig.tool_name == "jira",
            )
        )
    ).scalar_one()
    assert entry.is_active is True
    assert entry.config == {"jira_allowed_projects": ["RIVER"]}


@pytest.mark.asyncio
async def test_project_connector_access_lists_configured_global_connectors_dynamically(db):
    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    await upsert_tool_config(
        db,
        tool_name="aws",
        project_id=None,
        config={
            "aws_region": "eu-central-1",
            "aws_allowed_services": ["rds"],
        },
        is_active=True,
    )
    await db.flush()

    payload = await list_project_connector_access(db, project_id=demo_project.id)
    aws = next(item for item in payload["connectors"] if item["connector_name"] == "aws")

    assert aws["label"] == "AWS"
    assert aws["global_configured"] is True
    assert aws["global_active"] is True
    assert aws["project_enabled"] is False
    assert aws["limit_fields"] == ["aws_allowed_services"]
    assert aws["inherited_limits"] == {"aws_allowed_services": ["rds"]}


@pytest.mark.asyncio
async def test_project_connector_access_api_saves_dynamic_aws_limits(client, db):
    login_resp = await client.post(
        "/admin/login",
        data={"username": "admin", "password": ADMIN_PASSWORD},
    )
    assert login_resp.status_code == 303

    demo_project = (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()
    response = await client.put(
        f"/admin/chat/api/panel/projects/{demo_project.id}/connectors/aws",
        json={
            "is_active": True,
            "limits": {
                "aws_allowed_services": ["ec2", "rds"],
                "aws_region": "should-not-be-project-scoped",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    aws = next(item for item in payload["connectors"] if item["connector_name"] == "aws")
    assert aws["project_enabled"] is True
    assert aws["project_limits"] == {"aws_allowed_services": ["ec2", "rds"]}

    await db.rollback()
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id == demo_project.id,
                BuiltInToolConfig.tool_name == "aws",
            )
        )
    ).scalar_one()
    assert entry.is_active is True
    assert entry.config == {"aws_allowed_services": ["ec2", "rds"]}
