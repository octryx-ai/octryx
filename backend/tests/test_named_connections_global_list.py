"""The global connection list shows ids, the last test and every active Workspace's own connections without a secret, and a Workspace connection is tested with its stored secret."""

from __future__ import annotations

import json
import uuid

import pytest

import app.web.routers.panel_named_connections as routes
from app.models import BuiltInToolConfig, Project
from app.services.admin.project.named_connection_view import list_named
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.named_connections_global_support import (
    FAKE_A,
    FAKE_B,
    OTHER_WIKI,
    PANEL,
    WIKI,
    _body,
    _login,
    _no_secret,
    _save,
    _workspace,
)

pytestmark = pytest.mark.usefixtures("public_source_dns")


async def test_the_global_list_shows_ids_last_test_and_never_a_secret(client, db, monkeypatch) -> None:
    await _login(client)
    url = f"{PANEL}/connectors/confluence/named-connections"
    created = (await client.post(url, json=_body("client-a", ["SALES"], FAKE_A))).json()
    connection_id = created["id"]
    assert uuid.UUID(connection_id) and created["last_test"] is None

    async def fake_test(tool: str, config: dict, *, db=None, scope_check=False) -> dict:
        assert db is not None
        return {"ok": config["confluence_token"] == FAKE_A, "summary": "Connected as svc-a", "details": FAKE_A}

    monkeypatch.setattr(routes, "run_connector_connection_test", fake_test)
    assert (await client.post(f"{url}/{connection_id}/test", json={})).json()["ok"] is True

    listed = (await client.get(url)).json()
    _no_secret(listed)
    (row,) = listed["connections"]
    assert row["id"] == connection_id and row["scope"] == "global"
    assert row["last_test"]["ok"] is True and row["last_test"]["summary"] == "Connected as svc-a"
    assert row["last_test"]["at"]
    assert row["usage"] == {"workspaces": [], "knowledge_connectors": [], "work_intakes": []}
    assert listed["default"]["id"] == "default" and "inherited" not in listed

    # A test with typed values says nothing about the saved connection: not kept.
    failed = await client.post(f"{url}/{connection_id}/test", json={"confluence_token": FAKE_B})
    assert failed.json()["ok"] is False
    assert (await client.get(url)).json()["connections"][0]["last_test"]["ok"] is True

    # A changed account clears it (the old result says nothing about the new secret).
    await client.put(f"{url}/{connection_id}", json={"confluence_token": FAKE_B})
    assert (await client.get(url)).json()["connections"][0]["last_test"] is None


async def test_the_global_list_shows_every_active_workspaces_own_connections(db) -> None:
    workspace_id = await _workspace(db, spaces=("ENG",))
    own = await _save(db, workspace_id, _body("client-a", ["SALES"], FAKE_A))
    archived = await _workspace(db)
    (await db.get(Project, archived)).is_active = False
    access_only = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=access_only, config={"confluence_allowed_spaces": []}))
    await db.flush()

    listed = (await list_named(db, connector="confluence", project_id=None))["workspace_connections"]

    mine = [item for item in listed if item["workspace_id"] in (workspace_id, archived, access_only)]
    assert [(item["workspace_id"], item["id"], item["bound_scopes"]) for item in mine] == [
        (workspace_id, "default", ["ENG"]), (workspace_id, own["id"], ["SALES"]),
    ]
    assert mine[0]["fields"]["confluence_url"] == WIKI and mine[1]["name"] == "client-a"
    assert "fake-default" not in json.dumps(listed)
    _no_secret(listed)
    assert "workspace_connections" not in await list_named(db, connector="confluence", project_id=workspace_id)


async def test_a_workspace_connection_is_tested_with_its_stored_secret_whatever_the_global_target(
    client, db, monkeypatch
) -> None:
    await _login(client)
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=None, config={
        "confluence_url": OTHER_WIKI, "confluence_auth_mode": "oidc_client_credentials",
        "confluence_oidc_token_url": "https://idp.example.test/token", "confluence_oidc_client_id": "svc"}))
    workspace_id = await _workspace(db)
    await db.commit()
    url = f"{PANEL}/projects/{workspace_id}/connectors/confluence/named-connections"
    connection_id = (await client.post(url, json=_body("client-a", ["SALES"], FAKE_A))).json()["id"]

    async def fake_test(tool: str, config: dict, *, db=None, scope_check=False) -> dict:
        return {"ok": config["confluence_token"] == FAKE_A, "summary": "Connected"}

    monkeypatch.setattr(routes, "run_connector_connection_test", fake_test)
    tested = await client.post(f"{url}/{connection_id}/test", json={})
    assert tested.status_code == 200 and tested.json()["ok"] is True
    renamed = await client.put(f"{url}/{connection_id}", json={**_body("client-b", ["SALES"])})
    assert renamed.status_code == 200 and renamed.json()["name"] == "client-b"
