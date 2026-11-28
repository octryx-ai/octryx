"""Contract: a Jira connector save with an explicit sign-in mode."""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import select

from app.models import BuiltInToolConfig, StoredSecret
from app.services.connector_auth.atlassian import auth_headers

ROUTE = "/admin/chat/api/panel/connectors/jira"
JIRA_A = "https://jira-a.example.test"
JIRA_B = "https://jira-b.example.test"
TO_SERVER = {"jira_auth_mode": "basic", "jira_username": "svc-jira", "jira_password": "pw-new"}


async def _jira_config(db) -> dict:
    await db.rollback()
    row = (
        await db.execute(
            select(BuiltInToolConfig).where(
                BuiltInToolConfig.tool_name == "jira", BuiltInToolConfig.project_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    return dict(row.config) if row else {}


async def _jira_secrets(db) -> list[str]:
    await db.rollback()
    rows = (await db.execute(select(StoredSecret.field_name).where(StoredSecret.tool_name == "jira"))).scalars().all()
    return sorted(rows)


async def _cloud(client, url: str = JIRA_A) -> None:
    saved = await client.put(ROUTE, json={"jira_url": url, "jira_auth_mode": "cloud_api_token",
                                          "jira_email": "bot@example.test", "jira_token": "tok-1"})
    assert saved.status_code == 200, saved.text


@pytest.mark.asyncio
async def test_switching_cloud_to_server_reads_only_the_new_modes_pair(admin_client, db):
    await _cloud(admin_client)
    saved = await admin_client.put(ROUTE, json=dict(TO_SERVER))
    assert saved.status_code == 200, saved.text
    config = await _jira_config(db)
    assert config["jira_auth_mode"] == "basic" and "jira_password_secret_ref" in config
    # The Cloud token stays stored but the explicit mode never reads it.
    basic = "Basic " + base64.b64encode(b"svc-jira:pw-new").decode()
    assert auth_headers("jira", {**config, "jira_password": "pw-new", "jira_token": "tok-1"}) == {"Authorization": basic}
    assert await _jira_secrets(db) == ["jira_password", "jira_token"]


@pytest.mark.asyncio
async def test_credentials_without_a_mode_are_refused_before_any_write(admin_client, db):
    refused = await admin_client.put(ROUTE, json={"jira_url": JIRA_A, "jira_email": "bot@example.test",
                                            "jira_token": "tok-1"})
    assert refused.status_code == 422, refused.text
    assert await _jira_config(db) == {} and await _jira_secrets(db) == []


@pytest.mark.asyncio
async def test_a_retained_secret_still_needs_rebind_and_nothing_is_stored_on_refusal(admin_client, db):
    await _cloud(admin_client, JIRA_A)
    # A Server pair on a new URL: the stored Cloud token would be carried to JIRA_B.
    refused = await admin_client.put(ROUTE, json={**TO_SERVER, "jira_url": JIRA_B})
    assert refused.status_code == 409
    assert refused.json()["detail"]["kept_fields"] == ["jira_token"]
    config = await _jira_config(db)
    assert config["jira_url"] == JIRA_A and "jira_password_secret_ref" not in config
    assert await _jira_secrets(db) == ["jira_token"], "a refused save stores no secret"


@pytest.mark.asyncio
async def test_an_ordinary_save_keeps_stored_credentials_and_clears_scope_on_empty(admin_client, db):
    await _cloud(admin_client)
    restricted = await admin_client.put(ROUTE, json={"jira_allowed_projects": ["OPS", "RIVER"]})
    assert restricted.status_code == 200
    config = await _jira_config(db)
    assert config["jira_allowed_projects"] == ["OPS", "RIVER"] and "jira_token_secret_ref" in config
    cleared = await admin_client.put(ROUTE, json={"jira_allowed_projects": ""})
    assert cleared.status_code == 200
    config = await _jira_config(db)
    assert "jira_allowed_projects" not in config and config["jira_email"] == "bot@example.test"
    assert "jira_token_secret_ref" in config
