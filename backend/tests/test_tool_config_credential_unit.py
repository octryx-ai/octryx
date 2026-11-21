"""Contract: a connection's credential is one unit per scope, never mixed field by field.

A Workspace entry that sets any credential (secret or principal) or target field of a connection
inherits none of the global credential fields; limits and allowlists still merge, and a global
target only when the Workspace entry holds no secret of its own.
Covered for the tools' project config, Source Sync's connection and the secure_work Jira sync.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.atlassian_auth_modes import AtlassianAuthConfigError
from app.services.knowledge.sources.sync.connections import resolve_connection
from app.services.knowledge.sources.sync.contract import REASON_OWN_CONNECTION_INCOMPLETE, ConnectorError
from app.services.project import get_project_config
from app.services.secret import set_secret_value
from app.services.secure_work.jira.jira_connector import _resolve_jira_connector_config
from app.services.tool_config import upsert_tool_config
from app.services.tool_config.connection_fields import credential_unit_keys, target_fields

GLOBAL_WIKI = "https://wiki.example.test/wiki"


async def _demo(db) -> Project:
    return (await db.execute(select(Project).where(Project.name == "demo"))).scalar_one()


async def _config(db, tool: str, project_id: str | None, config: dict, secrets: dict[str, str] | None = None) -> None:
    stored = dict(config)
    for field, value in (secrets or {}).items():
        entry = await set_secret_value(db, tool_name=tool, field_name=field, project_id=project_id, value=value)
        stored[f"{field}_secret_ref"] = entry.id
    await upsert_tool_config(db, tool_name=tool, project_id=project_id, config=stored, is_active=True)
    await db.flush()


async def _global_confluence(db) -> None:
    await _config(
        db,
        "confluence",
        None,
        {
            "confluence_url": GLOBAL_WIKI,
            "confluence_auth_mode": "basic",
            "confluence_username": "global-bot",
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        },
        {"confluence_password": "global-password"},
    )


def test_the_credential_unit_is_the_secrets_their_refs_and_the_principals():
    assert credential_unit_keys("confluence") == {
        "confluence_username",
        "confluence_password",
        "confluence_token",
        "confluence_password_secret_ref",
        "confluence_token_secret_ref",
        "confluence_auth_mode",  # how the credential is sent belongs to the unit
        # the client credentials of the OpenID Connect mode and its options
        "confluence_oidc_client_id",
        "confluence_oidc_client_secret",
        "confluence_oidc_client_secret_secret_ref",
        "confluence_oidc_scope",
        "confluence_oidc_audience",
        "confluence_oidc_client_auth",
    }
    assert credential_unit_keys("jira") >= {"jira_email", "jira_username", "jira_token", "jira_password", "jira_auth_mode"}
    assert "jira_allowed_projects" not in credential_unit_keys("jira")
    assert target_fields("servicenow") == ("servicenow_url", "servicenow_token_url")
    assert target_fields("jira") == ("jira_url", "jira_oidc_token_url")  # the token endpoint is a target too


@pytest.mark.asyncio
async def test_a_workspace_token_never_pairs_with_the_global_password(db):
    project = await _demo(db)
    await _global_confluence(db)
    await _config(db, "confluence", project.id, {"confluence_auth_mode": "cloud_api_token", "confluence_username": "ws-bot"},
                  {"confluence_token": "ws-token"})

    config = await get_project_config(project.id, db)
    assert config["confluence_token"] == "ws-token"
    assert config["confluence_username"] == "ws-bot"
    assert "confluence_password" not in config and "confluence_password_secret_ref" not in config
    # Non-credential fields still merge; the global target does not (own secret, own target).
    assert "confluence_url" not in config
    assert config["confluence_allowed_spaces"] == [{"space_key": "ENG", "enabled": True}]

    # Fail closed: the Workspace secret has no target of its own, so there is no connection.
    with pytest.raises(ConnectorError) as refused:
        await resolve_connection(db, kind="confluence", project_id=project.id)
    assert refused.value.reason == REASON_OWN_CONNECTION_INCOMPLETE  # named, not generic


@pytest.mark.asyncio
async def test_a_partial_workspace_credential_is_not_completed_from_the_global_entry(db):
    project = await _demo(db)
    await _global_confluence(db)
    # Only a token: the global principal does not complete it; the save itself is refused.
    with pytest.raises(AtlassianAuthConfigError, match="Confluence username"):
        await _config(db, "confluence", project.id, {"confluence_auth_mode": "cloud_api_token"},
                      {"confluence_token": "ws-token"})

    assert "confluence_username" not in await get_project_config(project.id, db)


@pytest.mark.asyncio
async def test_a_workspace_url_never_receives_the_global_credential(db):
    project = await _demo(db)
    await _global_confluence(db)
    await _config(db, "confluence", project.id, {"confluence_url": "https://other.example.test/wiki"})

    config = await get_project_config(project.id, db)
    assert config["confluence_url"] == "https://other.example.test/wiki"
    assert "confluence_password" not in config and "confluence_username" not in config
    with pytest.raises(ConnectorError):
        await resolve_connection(db, kind="confluence", project_id=project.id)


@pytest.mark.asyncio
async def test_a_workspace_that_sets_only_limits_inherits_the_global_credential(db):
    project = await _demo(db)
    await _global_confluence(db)
    await _config(db, "confluence", project.id, {"confluence_allowed_spaces": [{"space_key": "OPS", "enabled": True}]})

    config = await get_project_config(project.id, db)
    assert config["confluence_allowed_spaces"] == [{"space_key": "OPS", "enabled": True}]
    assert (config["confluence_username"], config["confluence_password"]) == ("global-bot", "global-password")
    connection = await resolve_connection(db, kind="confluence", project_id=project.id)
    assert (connection.principal, connection.secret) == ("global-bot", "global-password")


@pytest.mark.asyncio
async def test_the_secure_work_jira_sync_does_not_remix_the_global_credential(db):
    project = await _demo(db)
    await _config(
        db,
        "jira",
        None,
        {"jira_url": "https://jira.example.test", "jira_auth_mode": "basic", "jira_username": "global-bot"},
        {"jira_password": "global-password"},
    )
    await _config(db, "jira", project.id, {"jira_auth_mode": "cloud_api_token", "jira_email": "ws@example.test"},
                  {"jira_token": "ws-token"})

    class _SyncConfig:  # the WorkItemSyncConfig fields the intake's connection lookup reads
        project_id = project.id
        connection_id = None  # the Workspace's default connection
        filters_json: dict = {}

    config = await _resolve_jira_connector_config(db, _SyncConfig())
    assert (config["jira_email"], config["jira_token"]) == ("ws@example.test", "ws-token")
    assert "jira_password" not in config and "jira_username" not in config
    assert "jira_url" not in config, "a Workspace secret never goes to the inherited global target"
