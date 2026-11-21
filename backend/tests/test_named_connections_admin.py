"""Admin API of named connections, through the real panel routes.

- secrets are write-only: no response carries a secret value or a ``*_secret_ref``; the secret is
  stored for this connection alone (``<field>#<id>``) and resolved for its connection test;
- refused at save with fixed codes: the reserved name ``default``, a taken name, a scope another
  connection binds (409, naming the other connection), an incomplete unit (422);
- a kept secret never silently follows a changed URL (409 ``secret_rebind_required``);
- delete removes the connection and releases its secrets;
- create, update, test and delete are audited with names and keys only, never a secret value;
- the global scope has the same routes.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, ConnectorNamedConnection, Project, StoredSecret
from tests.conftest import ADMIN_PASSWORD

PANEL = "/admin/chat/api/panel"
WIKI = "https://wiki.example.test/wiki"
FAKE_A = "fake-pat-a-123"
FAKE_B = "fake-pat-b-456"


async def _login(client) -> None:
    response = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert response.status_code == 303


async def _project(db) -> str:
    project = Project(name=f"named-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.flush()
    db.add(BuiltInToolConfig(tool_name="confluence", project_id=project.id, is_active=True,
                             config={"confluence_url": WIKI, "confluence_allowed_spaces": ["ENG"]}))
    await db.commit()
    return project.id


def _body(name: str, scopes: list[str], **extra) -> dict:
    return {"name": name, "bound_scopes": scopes, "confluence_url": WIKI, "confluence_auth_mode": "bearer_pat",
            **extra}


def _no_secret(payload: object) -> None:
    text = json.dumps(payload)
    assert FAKE_A not in text and FAKE_B not in text and "_secret_ref" not in text


async def test_named_connections_are_created_listed_and_never_return_a_secret(client, db) -> None:
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/named-connections"

    created = await client.post(url, json=_body("client-a", ["sales", "INFRA"], confluence_token=FAKE_A))

    assert created.status_code == 201, created.text
    connection = created.json()
    _no_secret(connection)
    assert connection["bound_scopes"] == ["SALES", "INFRA"]
    assert connection["secret_status"] == {"confluence_password": False, "confluence_token": True,
                                           "confluence_oidc_client_secret": False}
    secret = (await db.execute(select(StoredSecret).where(StoredSecret.project_id == project_id))).scalar_one()
    assert secret.field_name == f"confluence_token#{connection['id']}" and secret.encrypted_value != FAKE_A

    listed = (await client.get(url)).json()
    _no_secret(listed)
    assert listed["default"]["name"] == "default" and listed["default"]["active"] is True
    assert [item["name"] for item in listed["connections"]] == ["client-a"]


async def test_reserved_and_taken_names_double_bindings_and_incomplete_units_are_refused(client, db) -> None:
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/named-connections"
    assert (await client.post(url, json=_body("client-a", ["SALES"], confluence_token=FAKE_A))).status_code == 201

    cases = [
        (_body("default", ["X"], confluence_token=FAKE_B), 422, "named_connection_name_reserved"),
        (_body("CLIENT-A", ["X"], confluence_token=FAKE_B), 409, "named_connection_name_taken"),
        (_body("client-b", ["INFRA", "sales"], confluence_token=FAKE_B), 409, "named_connection_scope_bound_twice"),
        (_body("client-b", ["INFRA"]), 422, "atlassian_auth_invalid"),
        (_body("client-b", []), 422, "named_connection_scopes_invalid"),
    ]
    for body, status, code in cases:
        response = await client.post(url, json=body)
        assert response.status_code == status, (body["name"], response.text)
        assert response.json()["detail"]["code"] == code
        _no_secret(response.json())
    assert "client-a" in (await client.post(url, json=cases[2][0])).json()["detail"]["message"]
    rows = (await db.execute(select(ConnectorNamedConnection))).scalars().all()
    assert [row.name for row in rows] == ["client-a"]
    assert (await client.get(f"{PANEL}/projects/{project_id}/connectors/pagerduty/named-connections")).status_code == 404


async def test_a_kept_secret_never_follows_a_changed_url_without_confirmation(client, db) -> None:
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/named-connections"
    connection_id = (await client.post(url, json=_body("client-a", ["SALES"], confluence_token=FAKE_A))).json()["id"]

    moved = {"confluence_url": "https://other.example.test/wiki"}
    refused = await client.put(f"{url}/{connection_id}", json=moved)
    assert refused.status_code == 409 and refused.json()["detail"]["state"] == "secret_rebind_required"

    confirmed = await client.put(f"{url}/{connection_id}", json={**moved, "confirm_secret_rebind": True})
    assert confirmed.status_code == 200 and confirmed.json()["fields"]["confluence_url"] == moved["confluence_url"]
    renamed = await client.put(f"{url}/{connection_id}", json={"name": "sales-account", "bound_scopes": ["SALES", "OPS"]})
    assert renamed.json()["name"] == "sales-account" and renamed.json()["bound_scopes"] == ["SALES", "OPS"]
    assert renamed.json()["secret_status"]["confluence_token"] is True


async def test_test_uses_the_connections_own_secret_and_everything_is_audited(client, db, monkeypatch) -> None:
    import app.web.routers.panel_named_connections as routes

    seen: list[dict] = []

    async def fake_test(tool: str, config: dict, *, db=None, scope_check=False) -> dict:
        # The test gets the request's session, so tool helpers resolve as in a real call.
        assert db is not None
        seen.append({"tool": tool, **config})
        return {"ok": True, "summary": "Connected"}

    monkeypatch.setattr(routes, "run_connector_connection_test", fake_test)
    await _login(client)
    project_id = await _project(db)
    url = f"{PANEL}/projects/{project_id}/connectors/confluence/named-connections"
    connection_id = (await client.post(url, json=_body("client-a", ["SALES"], confluence_token=FAKE_A))).json()["id"]

    tested = await client.post(f"{url}/{connection_id}/test", json={})
    typed = await client.post(f"{url}/{connection_id}/test", json={"confluence_token": FAKE_B})

    assert tested.json() == {"ok": True, "summary": "Connected"} and typed.json()["ok"] is True
    assert seen[0]["confluence_token"] == FAKE_A and seen[1]["confluence_token"] == FAKE_B
    assert all("_secret_ref" not in key for entry in seen for key in entry)
    # The typed secret was used for the test only: the stored one is unchanged.
    secret = (await db.execute(select(StoredSecret).where(StoredSecret.project_id == project_id))).scalar_one()
    stored_id = secret.id

    deleted = await client.delete(f"{url}/{connection_id}")
    assert deleted.status_code == 200 and deleted.json()["stored_entries"]["deleted"][0]["id"] == stored_id
    db.expire_all()
    assert (await db.execute(select(StoredSecret).where(StoredSecret.project_id == project_id))).first() is None
    assert (await db.get(ConnectorNamedConnection, connection_id)) is None

    audits = (await db.execute(select(AuditLog).where(AuditLog.resource_type == "named_connection"))).scalars().all()
    assert [row.action for row in audits].count("admin.named_connection.tested") == 2
    assert {row.action for row in audits} == {
        "admin.named_connection.created", "admin.named_connection.tested", "admin.named_connection.deleted",
    }
    for row in audits:
        assert row.resource_id.endswith(connection_id) and row.details["connection_name"] == "client-a"
        assert FAKE_A not in json.dumps(row.details) and FAKE_B not in json.dumps(row.details)


async def test_the_global_scope_has_its_own_named_connections(client, db) -> None:
    await _login(client)
    url = f"{PANEL}/connectors/jira/named-connections"
    created = await client.post(url, json={
        "name": "ops", "bound_scopes": ["OPS"], "jira_url": "https://jira.example.test",
        "jira_auth_mode": "bearer_pat", "jira_token": FAKE_A,
    })
    assert created.status_code == 201, created.text
    assert created.json()["scope"] == "global"
    _no_secret((await client.get(url)).json())
    row = await db.get(ConnectorNamedConnection, created.json()["id"])
    assert row.project_id is None and row.scope_key == "global"
