"""A public GitHub connection without sign-in (E2 step 2, fresh-install finding)."""

from __future__ import annotations

import uuid

import pytest

from app.models import ConnectorNamedConnection
from app.services.knowledge.sources.sync.connections import PublicGitConnection
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.scope_connections import resolve_scope_connections
from app.services.named_connections.grants import grant_for
from tests.factories import make_project
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/admin"
REMOTE = {"remote": "https://github.com/octo/public-repo", "fetch_mode": "remote_git"}


async def _workspace(db) -> str:
    return (await make_project(db, name=f"ws-{uuid.uuid4().hex[:6]}", commit=True)).id


def _body(workspace_id: str, access: dict) -> dict:
    return {"type": "github", "name": f"public-{uuid.uuid4().hex[:4]}", "access": access,
            "available_in": "selected", "workspaces": [workspace_id], "bound_scopes": ["octo"]}


async def test_a_public_github_connection_needs_no_credential_and_only_reads(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    created = await client.post(f"{BASE}/connections", headers=bearer(admin),
                                json=_body(workspace_id, {"auth": "none", "github_owner": "octo"}))
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["access"]["secret_set"] is False and detail["uses"]["agent_tools"]["level"] == "read"
    assert detail["access"]["auth"] == "none"
    url = f"{BASE}/connections/{detail['id']}"

    write = await client.put(url, headers=bearer(admin), json={"uses": {"agent_tools": {"level": "write"}}})
    assert write.status_code == 422
    assert write.json()["detail"]["code"] == "agent_tools_level_requires_credentials"
    assert (await client.put(url, headers=bearer(admin), json={"uses": {"agent_tools": {"level": "off"}}})
            ).status_code == 200

    secret = await client.post(f"{BASE}/connections", headers=bearer(admin), json=_body(
        workspace_id, {"auth": "none", "github_token": "fake-token"}))
    assert secret.status_code == 422 and secret.json()["detail"]["field"] == "access.github_token"
    token = await client.post(f"{BASE}/connections", headers=bearer(admin),
                              json=_body(workspace_id, {"auth": "token", "github_owner": "octo"}))
    assert token.status_code == 422 and token.json()["detail"]["field"] == "access.github_token"
    unknown = await client.post(f"{BASE}/connections", headers=bearer(admin),
                                json=_body(workspace_id, {"auth": "password"}))
    assert unknown.status_code == 422 and unknown.json()["detail"]["field"] == "access.auth"


async def test_a_stored_write_level_is_served_as_read_without_a_credential(db) -> None:
    workspace_id = await _workspace(db)
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="github", project_id=None, scope_key="global",
                                   name="public", bound_scopes=["octo"], config={"github_owner": "octo"},
                                   available_in="all", agent_tools_level="write")
    db.add(row)
    await db.flush()
    assert (await grant_for(db, row, workspace_id)).level == "read"


async def test_a_repository_source_linked_to_a_public_connection_syncs_anonymously(db) -> None:
    workspace_id = await _workspace(db)
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="github", project_id=None, scope_key="global",
                                   name="public", bound_scopes=["octo"], config={"github_owner": "octo"},
                                   available_in="selected", owner_kind="workspace", owner_workspace_id=workspace_id)
    db.add(row)
    await db.flush()
    scoped = await resolve_scope_connections(db, kind="git_repository", project_id=workspace_id, scope=dict(REMOTE),
                                             connection_id=row.id)
    assert isinstance(scoped.single, PublicGitConnection), "no credential is read for a public repository"

    row.is_active = False
    await db.flush()
    with pytest.raises(ConnectorError) as disabled:
        await resolve_scope_connections(db, kind="git_repository", project_id=workspace_id, scope=dict(REMOTE),
                                        connection_id=row.id)
    assert disabled.value.reason == "connection_disabled"
    with pytest.raises(ConnectorError) as elsewhere:
        await resolve_scope_connections(db, kind="git_repository", project_id=str(uuid.uuid4()), scope=dict(REMOTE),
                                        connection_id=row.id)
    assert elsewhere.value.reason == "connection_not_available"
