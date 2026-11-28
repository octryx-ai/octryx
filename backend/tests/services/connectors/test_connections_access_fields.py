"""Connections API: access fields per sign-in kind and readable recent errors."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.models import KnowledgeSourceConnector, User, WorkItemSyncConfig, WorkItemSyncRun
from app.models.project.knowledge_source_sync import KnowledgeSourceSyncRun
from app.services.connections.error_sentences import sentence
from app.time_utils import utc_now
from tests.factories import make_project
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/admin"
URL = "https://jira.example.test"


async def _workspace(db) -> str:
    return (await make_project(db, name=f"ws-{uuid.uuid4().hex[:6]}", commit=True)).id


def _body(workspace_id: str, access: dict, name: str = "Jira") -> dict:
    return {"type": "jira", "name": f"{name}-{uuid.uuid4().hex[:4]}", "access": {"jira_url": URL, **access},
            "available_in": "selected", "workspaces": [workspace_id], "bound_scopes": ["OPS"]}


async def test_each_access_field_names_its_sign_in_kinds(client, db) -> None:
    admin = await make_user(db, admin=True)
    types = {item["type"]: item for item in (await client.get(f"{BASE}/connection-types",
                                                               headers=bearer(admin))).json()}
    jira = {field["key"]: field for field in types["jira"]["access_fields"]}
    every = types["jira"]["auth_kinds"]
    assert jira["jira_url"]["auth_kinds"] == every and jira["jira_url"]["required"] is True
    assert jira["jira_email"]["auth_kinds"] == ["cloud_api_token"] and jira["jira_email"]["required"] is True
    assert jira["jira_username"]["auth_kinds"] == ["basic"] and jira["jira_password"]["auth_kinds"] == ["basic"]
    assert jira["jira_token"]["auth_kinds"] == ["cloud_api_token", "bearer_pat"]
    assert jira["jira_oidc_scope"] == {**jira["jira_oidc_scope"], "auth_kinds": ["oidc_client_credentials"],
                                       "required": False}
    servicenow = {field["key"]: field for field in types["servicenow"]["access_fields"]}
    assert servicenow["servicenow_token"]["auth_kinds"] == ["bearer_token"]
    github = {field["key"]: field for field in types["github"]["access_fields"]}
    assert types["github"]["auth_kinds"] == ["token", "none"], "a public repository needs no credential"
    assert github["github_token"]["auth_kinds"] == ["token"] and github["github_token"]["required"] is True
    assert github["github_owner"]["auth_kinds"] == ["token", "none"]
    assert all(field["auth_kinds"] == ["token"] for field in types["kubernetes"]["access_fields"])


async def test_a_required_field_is_required_only_for_the_chosen_sign_in_kind(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    basic = await client.post(f"{BASE}/connections", headers=bearer(admin), json=_body(
        workspace_id, {"jira_auth_mode": "basic", "jira_password": "fake-pass"}))
    assert basic.status_code == 422
    assert basic.json()["detail"] == {"code": "connection_field_invalid", "field": "access.jira_username",
                                      "message": "access.jira_username is required for this sign-in kind."}
    bearer_only = await client.post(f"{BASE}/connections", headers=bearer(admin), json=_body(
        workspace_id, {"jira_auth_mode": "bearer_pat", "jira_token": "fake-token"}))
    assert bearer_only.status_code == 201, "no email or username for a personal access token"
    switched = await client.put(f"{BASE}/connections/{bearer_only.json()['id']}", headers=bearer(admin),
                                json={"access": {"jira_auth_mode": "cloud_api_token"}})
    assert switched.status_code == 422 and switched.json()["detail"]["field"] == "access.jira_email"


async def test_recent_errors_carry_the_code_and_one_sentence(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    created = await client.post(f"{BASE}/connections", headers=bearer(admin), json=_body(
        workspace_id, {"jira_auth_mode": "bearer_pat", "jira_token": "fake-token"}))
    connection_id = created.json()["id"]
    admin_row = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    intake = WorkItemSyncConfig(name="Ops", project_id=workspace_id, source_type="jira", connection_id=connection_id,
                                created_by=admin_row.id)
    source = KnowledgeSourceConnector(project_id=workspace_id, connector_key="ops", kind="jira", scope={},
                                      connection_id=connection_id)
    db.add_all([intake, source])
    await db.flush()
    now = utc_now()
    db.add(WorkItemSyncRun(sync_config_id=intake.id, triggered_by=admin_row.id, status="failed", error="jql_invalid",
                           created_at=now - timedelta(minutes=2)))
    db.add(KnowledgeSourceSyncRun(connector_id=source.id, project_id=workspace_id, state="failed",
                                  reason="brand_new_code", report={}, outcomes=[], started_at=now,
                                  finished_at=now))
    await db.commit()

    detail = (await client.get(f"{BASE}/connections/{connection_id}", headers=bearer(admin))).json()
    errors = detail["recent_errors"]
    assert [(item["use"], item["code"]) for item in errors] == [("knowledge", "brand_new_code"),
                                                               ("tickets", "jql_invalid")]
    assert errors[0]["message"] == "The knowledge sync failed (brand_new_code)."
    assert errors[1]["message"] == "Jira refused the intake's query (JQL)."
    assert all(set(item) == {"at", "use", "code", "message"} and item["message"] for item in errors)
    assert sentence("", "tickets") == "The tickets sync failed (unknown)."
