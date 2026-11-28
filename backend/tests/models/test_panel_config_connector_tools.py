"""The tool catalog's active connector tools, refused tool config shapes and AWS static credentials saved as secret references."""

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, StoredSecret


@pytest.mark.asyncio
async def test_tool_catalog_shows_active_configured_connector_tools(admin_client, db):
    initial_resp = await admin_client.get("/admin/chat/api/panel/tool-catalog")
    assert initial_resp.status_code == 200
    initial_names = {entry["name"] for entry in initial_resp.json()}
    assert "list_oncall" not in initial_names
    assert "create_incident" not in initial_names

    db.add(
        BuiltInToolConfig(
            tool_name="pagerduty",
            project_id=None,
            config={
                "incident_provider": "pagerduty",
                "pagerduty_url": "https://api.pagerduty.example",
                "pagerduty_token_secret_ref": "secret-id",
            },
            is_active=True,
        )
    )
    await db.commit()

    configured_resp = await admin_client.get("/admin/chat/api/panel/tool-catalog")
    assert configured_resp.status_code == 200
    configured_by_name = {entry["name"]: entry for entry in configured_resp.json()}
    assert configured_by_name["list_oncall"]["default_connector"] == "pagerduty"
    assert configured_by_name["list_oncall"]["connectors"] == ["pagerduty"]
    assert "create_incident" in configured_by_name
    assert configured_by_name["create_incident"]["connectors"] == ["pagerduty"]
    assert "list_github_action_runs" not in configured_by_name


@pytest.mark.asyncio
async def test_admin_panel_connector_save_rejects_invalid_tool_config_shape(admin_client):
    resp = await admin_client.put(
        "/admin/chat/api/panel/connectors/jira",
        json={
            "jira_url": "https://jira.example.com",
            "jira_allowed_projects": [{"key": "RIVER"}],
            "is_active": True,
        },
    )

    assert resp.status_code == 400
    assert "jira_allowed_projects must be a list of strings" in resp.text


@pytest.mark.asyncio
async def test_admin_panel_saves_aws_static_credentials_as_secret_refs(admin_client, db):
    resp = await admin_client.put(
        "/admin/chat/api/panel/connectors/aws",
        json={
            "is_active": True,
            "aws_region": "eu-central-1",
            "aws_access_key_id": "test-access-key",
            "aws_secret_access_key": "test-secret-key",
            "aws_session_token": "test-session-token",
            "aws_allowed_services": ["sts", "bedrock"],
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["supports_test"] is True
    assert payload["public_fields"]["aws_region"] == "eu-central-1"
    assert payload["public_fields"]["aws_allowed_services"] == ["sts", "bedrock"]
    assert "aws_access_key_id" not in payload["public_fields"]
    assert "aws_secret_access_key" not in payload["public_fields"]
    assert "aws_session_token" not in payload["public_fields"]
    assert payload["secret_status"] == {
        "aws_access_key_id": True,
        "aws_secret_access_key": True,
        "aws_session_token": True,
    }

    await db.rollback()
    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id.is_(None),
                BuiltInToolConfig.tool_name == "aws",
            )
        )
    ).scalar_one()
    assert "aws_access_key_id" not in entry.config
    assert "aws_secret_access_key" not in entry.config
    assert "aws_session_token" not in entry.config
    for field_name, raw_value in {
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        "aws_session_token": "test-session-token",
    }.items():
        secret_ref = entry.config[f"{field_name}_secret_ref"]
        secret = await db.get(StoredSecret, secret_ref)
        assert secret is not None
        assert secret.encrypted_value != raw_value
