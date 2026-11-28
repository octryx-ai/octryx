from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, ConnectorPolicy, StoredSecret
from app.services.admin.connector import (
    _admin_connector_activation,
    admin_connector_service,
)
from app.web._helpers.panel_serializers import _serialize_connector


def test_connector_activation_states_define_runtime_visibility_source_of_truth():
    states = {
        state["connector_name"]: state
        for state in _admin_connector_activation.list_connector_activation_states(
            [
                BuiltInToolConfig(
                    tool_name="pagerduty",
                    project_id=None,
                    config={},
                    is_active=True,
                ),
                BuiltInToolConfig(
                    tool_name="github",
                    project_id=None,
                    config={
                        "github_url": "https://api.github.com",
                        "github_token_secret_ref": "secret-id",
                        "github_owner": "sample",
                    },
                    is_active=False,
                ),
                BuiltInToolConfig(
                    tool_name="jira",
                    project_id=None,
                    config={
                        "jira_url": "https://jira.example.com",
                        "jira_token_secret_ref": "secret-id",
                    },
                    is_active=True,
                ),
            ]
        )
    }

    assert states["system"]["is_runtime_visible"] is True
    assert states["system"]["reason"] == "default_active"
    assert states["pagerduty"]["is_runtime_visible"] is False
    assert states["pagerduty"]["reason"] == "needs_configuration"
    assert states["github"]["is_runtime_visible"] is False
    assert states["github"]["reason"] == "connector_disabled"
    assert states["jira"]["is_runtime_visible"] is True
    assert states["jira"]["reason"] == "configured_active"
    assert states["jira"]["runtime_visibility_reason"] == "project_connector_config_present"


def test_connector_activation_state_requires_runtime_visible_config_key():
    states = {
        state["connector_name"]: state
        for state in _admin_connector_activation.list_connector_activation_states(
            [
                BuiltInToolConfig(
                    tool_name="jira",
                    project_id=None,
                    config={"jira_token_secret_ref": "secret-id"},
                    is_active=True,
                ),
            ]
        )
    }

    assert states["jira"]["is_configured"] is False
    assert states["jira"]["is_runtime_visible"] is False
    assert states["jira"]["reason"] == "needs_configuration"
    assert states["jira"]["runtime_visibility_reason"] == "connector_not_active_for_project"


@pytest.mark.asyncio
async def test_connector_tool_catalog_filters_inactive_and_unconfigured_connector_tools(db):
    initial_by_name = {entry["name"]: entry for entry in await _admin_connector_activation.list_tool_catalog_payload(db)}
    assert "list_oncall" not in initial_by_name
    assert "list_github_action_runs" not in initial_by_name

    db.add_all(
        [
            BuiltInToolConfig(
                tool_name="pagerduty",
                project_id=None,
                config={
                    "incident_provider": "pagerduty",
                    "pagerduty_url": "https://api.pagerduty.example",
                    "pagerduty_token_secret_ref": "secret-id",
                },
                is_active=True,
            ),
            BuiltInToolConfig(
                tool_name="github",
                project_id=None,
                config={
                    "github_url": "https://api.github.com",
                    "github_token_secret_ref": "secret-id",
                    "github_owner": "sample",
                },
                is_active=False,
            ),
        ]
    )
    await db.commit()

    configured_by_name = {entry["name"]: entry for entry in await _admin_connector_activation.list_tool_catalog_payload(db)}
    assert configured_by_name["list_oncall"]["connectors"] == ["pagerduty"]
    assert configured_by_name["list_oncall"]["runtime_visibility"]["visible"] is True
    assert configured_by_name["list_oncall"]["runtime_visibility"]["connector"] == "incident_management"
    assert "create_incident" in configured_by_name
    assert "list_github_action_runs" not in configured_by_name


@pytest.mark.asyncio
async def test_connector_tool_catalog_respects_connector_policy_disabled_tools(db):
    db.add_all(
        [
            BuiltInToolConfig(
                tool_name="jira",
                project_id=None,
                config={
                    "jira_url": "https://jira.example.com",
                    "jira_token_secret_ref": "secret-id",
                },
                is_active=True,
            ),
            ConnectorPolicy(
                connector_name="jira",
                project_id=None,
                policy={"disabled_tools": ["search_jira_tickets"]},
                is_active=True,
            ),
        ]
    )
    await db.commit()

    by_name = {entry["name"]: entry for entry in await _admin_connector_activation.list_tool_catalog_payload(db)}

    assert "search_jira_tickets" not in by_name
    assert by_name["get_jira_ticket"]["runtime_visibility"]["visible"] is True
    assert by_name["get_jira_ticket"]["connectors"] == ["jira"]


@pytest.mark.asyncio
async def test_save_connector_stores_secret_fields_as_secret_refs_and_redacts_payload(db, auth_user):
    result = await admin_connector_service.save_connector(
        db,
        tool_name="jira",
        payload={
            "jira_auth_mode": "cloud_api_token",
            "is_active": True,
            "jira_url": "https://jira.example.com",
            "jira_email": "agent@example.com",
            "jira_token": "jira-token-value",
        },
        serialize_connector=_serialize_connector,
        owner_id=auth_user.id,
    )

    assert result["is_active"] is True
    assert result["public_fields"]["jira_url"] == "https://jira.example.com"
    assert result["public_fields"]["jira_email"] == "agent@example.com"
    assert "jira_token" not in result["public_fields"]
    assert result["secret_status"]["jira_token"] is True

    entry = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.project_id.is_(None),
                BuiltInToolConfig.tool_name == "jira",
            )
        )
    ).scalar_one()
    assert "jira_token" not in entry.config
    secret_ref = entry.config["jira_token_secret_ref"]
    secret = await db.get(StoredSecret, secret_ref)
    assert secret is not None
    assert secret.encrypted_value != "jira-token-value"

    audit_log = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == "jira",
                AuditLog.action == "admin.connector.saved",
            )
        )
    ).scalar_one()
    assert audit_log.user_id == auth_user.id
    assert audit_log.resource_type == "connector_config"
    assert audit_log.details["connector_name"] == "jira"
    assert audit_log.details["after"]["config"]["jira_token_secret_ref"] == "[redacted]"
    assert "jira_token" not in audit_log.details["after"]["config"]


@pytest.mark.asyncio
async def test_delete_connector_records_secret_safe_audit_log(db, auth_user):
    db.add(
        BuiltInToolConfig(
            tool_name="github",
            project_id=None,
            config={
                "github_url": "https://api.github.com",
                "github_token_secret_ref": "secret-id",
                "github_owner": "sample",
            },
            is_active=True,
        )
    )
    await db.commit()

    result = await admin_connector_service.delete_connector(
        db,
        tool_name="github",
        actor_user_id=auth_user.id,
    )

    assert result == {
        "status": "deleted",
        "stored_entries": {"deleted": [], "kept": [], "not_found": ["secret-id"]},
    }
    audit_log = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_id == "github",
                AuditLog.action == "admin.connector.deleted",
            )
        )
    ).scalar_one()
    assert audit_log.user_id == auth_user.id
    assert audit_log.details["before"]["config"]["github_token_secret_ref"] == "[redacted]"
    assert audit_log.details["after"] == {}
