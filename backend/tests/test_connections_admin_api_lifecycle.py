"""The connection test persists its state, delete refuses a connection in use, workspace admins manage only their own connections, and ServiceNow settings are kept and used."""

from __future__ import annotations

from sqlalchemy import select

from app.api.routes import connections_admin as routes
from app.models import ConnectorNamedConnection, KnowledgeSourceConnector, StoredSecret, UserProject
from tests.connections_admin_api_support import BASE, FAKE, _access, _clean, _create, _workspace
from tests.policy_engine_support import bearer, make_user


async def _workspace_admin(db, workspace_id: str, role: str = "admin") -> str:
    user_id = await make_user(db, admin=False)
    db.add(UserProject(user_id=user_id, project_id=workspace_id, role=role))
    await db.commit()
    return user_id


async def test_the_test_returns_checks_and_persists_the_state(client, db, monkeypatch) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    connection_id = (await _create(client, admin, workspace_id))["id"]
    seen: dict = {}

    async def fake_test(tool_name, config, *, db=None, scope_check=False):
        seen.update(tool=tool_name, token=config.get("jira_token"), allow=config.get("jira_allowed_projects"))
        return {"ok": seen.get("fail") is None, "summary": "401 Unauthorized" if seen.get("fail") else "Signed in."}

    monkeypatch.setattr(routes, "run_connector_connection_test", fake_test)
    result = _clean(await client.post(f"{BASE}/connections/{connection_id}/test", headers=bearer(admin)))
    assert seen["tool"] == "jira" and seen["token"] == FAKE, "the connection's own secret is resolved for the test"
    assert seen["allow"] == ["BRD", "OPS"], "tested as it serves calls: its bound keys"
    assert result["state"] == "ok" and result["state_reason"] is None and result["tested_at"]
    assert result["checks"][0] == {"use": "access", "ok": True, "message": "Signed in."}

    seen["fail"] = True
    failed = _clean(await client.post(f"{BASE}/connections/{connection_id}/test", headers=bearer(admin)))
    assert failed["state"] == "failing" and failed["state_reason"] == "401 Unauthorized"
    detail = _clean(await client.get(f"{BASE}/connections/{connection_id}", headers=bearer(admin)))
    assert detail["state"] == "failing" and detail["last_tested_at"] == failed["tested_at"]

    disabled = _clean(await client.put(f"{BASE}/connections/{connection_id}", headers=bearer(admin),
                                       json={"is_active": False}))
    assert disabled["state"] == "disabled"


async def test_delete_refuses_a_connection_in_use_and_releases_its_secrets(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    connection_id = (await _create(client, admin, workspace_id))["id"]
    source = KnowledgeSourceConnector(project_id=workspace_id, connector_key="brd-docs", kind="jira",
                                      scope={"project_keys": ["BRD"]}, connection_id=connection_id)
    db.add(source)
    await db.commit()
    detail = _clean(await client.get(f"{BASE}/connections/{connection_id}", headers=bearer(admin)))
    assert detail["uses"]["knowledge"]["sources"][0]["connector_key"] == "brd-docs"
    assert detail["uses"]["knowledge"]["scope"] == {"projects": ["BRD"]}

    refused = await client.delete(f"{BASE}/connections/{connection_id}", headers=bearer(admin))
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "connection_in_use"
    assert refused.json()["detail"]["uses"] == [{"use": "knowledge", "id": source.id, "name": "brd-docs",
                                                 "workspace_id": workspace_id}]

    source.connection_id = None
    await db.commit()
    deleted = await client.delete(f"{BASE}/connections/{connection_id}", headers=bearer(admin))
    assert deleted.status_code == 200 and deleted.json()["status"] == "deleted"
    assert await db.get(ConnectorNamedConnection, connection_id) is None
    assert (await db.execute(select(StoredSecret).where(
        StoredSecret.field_name == f"jira_token#{connection_id}"))).scalar_one_or_none() is None
    assert (await client.get(f"{BASE}/connections/{connection_id}", headers=bearer(admin))).status_code == 404


async def test_workspace_admins_see_their_connections_and_create_only_their_own(client, db) -> None:
    admin = await make_user(db, admin=True)
    own, foreign = await _workspace(db, "Own"), await _workspace(db, "Foreign")
    platform = await _create(client, admin, own)
    hidden = await _create(client, admin, foreign, name="Foreign Jira")
    ws_admin = await _workspace_admin(db, own)

    listed = _clean(await client.get(f"{BASE}/connections", headers=bearer(ws_admin)))["connections"]
    ids = {item["id"]: item for item in listed}
    assert platform["id"] in ids and hidden["id"] not in ids
    assert ids[platform["id"]]["can_edit"] is False, "platform-owned: read-only for a Workspace admin"
    assert (await client.get(f"{BASE}/connections/{hidden['id']}", headers=bearer(ws_admin))).status_code == 404
    edit = await client.put(f"{BASE}/connections/{platform['id']}", headers=bearer(ws_admin), json={"name": "x"})
    assert edit.status_code == 403

    everywhere = await client.post(f"{BASE}/connections", headers=bearer(ws_admin), json={
        "type": "jira", "name": "Team Jira", "access": _access(), "available_in": "all"})
    assert everywhere.status_code == 403 and everywhere.json()["detail"]["field"] == "available_in"
    elsewhere = await client.post(f"{BASE}/connections", headers=bearer(ws_admin), json={
        "type": "jira", "name": "Team Jira", "access": _access(), "available_in": "selected",
        "workspaces": [foreign]})
    assert elsewhere.status_code == 403
    mine = await client.post(f"{BASE}/connections", headers=bearer(ws_admin), json={
        "type": "jira", "name": "Team Jira", "access": _access(), "available_in": "selected", "workspaces": [own]})
    assert mine.status_code == 201, mine.text
    body = _clean(mine)
    assert body["owner"] == {"kind": "workspace", "workspace": {"id": own, "name": "Own"}} and body["can_edit"]
    renamed = await client.put(f"{BASE}/connections/{body['id']}", headers=bearer(ws_admin), json={"name": "Team"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Team"

    member = await _workspace_admin(db, own, role="member")
    assert (await client.get(f"{BASE}/connections", headers=bearer(member))).status_code == 403


async def test_servicenow_api_style_and_paths_are_set_kept_and_used_by_the_test(client, db, monkeypatch) -> None:
    """``access.servicenow_api_style`` is never dropped silently (the test would then read the Table API: 403)."""
    import app.services.connector_test.visible_scopes as visible_scopes
    from tests.servicenow_stub_support import CHANGES_PATH, INCIDENTS_PATH, StubInstance, config, stub_instance

    instance = next(stub_instance(monkeypatch, StubInstance(incidents=2, changes=1)))
    monkeypatch.setattr(visible_scopes, "egress_transport", lambda *_a, inner=None, **_k: inner or instance.transport())
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    unit = {key: value for key, value in config().items() if not key.startswith(("servicenow_api_style",
                                                                                  "servicenow_incidents",
                                                                                  "servicenow_changes"))}
    created = await client.post(f"{BASE}/connections", headers=bearer(admin), json={
        "type": "servicenow", "name": "ServiceNow (scripted)", "access": unit, "available_in": "selected",
        "workspaces": [workspace_id]})
    assert created.status_code == 201, created.text
    connection_id = created.json()["id"]
    types = {item["type"]: item for item in (await client.get(f"{BASE}/connection-types",
                                                              headers=bearer(admin))).json()}
    style = next(field for field in types["servicenow"]["access_fields"] if field["key"] == "servicenow_api_style")
    assert (style["kind"], style["options"], style["secret"]) == ("select", ["table", "scripted"], False)

    refused = await client.put(f"{BASE}/connections/{connection_id}", headers=bearer(admin), json={
        "access": {"servicenow_api_style": "scripted"}})
    assert refused.status_code == 422 and "servicenow_incidents_path" in refused.text, "scripted needs a path"

    updated = await client.put(f"{BASE}/connections/{connection_id}", headers=bearer(admin), json={"access": {
        "servicenow_api_style": "scripted", "servicenow_incidents_path": INCIDENTS_PATH,
        "servicenow_changes_path": CHANGES_PATH, "servicenow_page_size": "50"}})  # the form sends text
    assert updated.status_code == 200, updated.text
    fields = updated.json()["access"]["fields"]
    assert fields["servicenow_api_style"] == "scripted" and fields["servicenow_incidents_path"] == INCIDENTS_PATH
    assert fields["servicenow_page_size"] == 50
    renamed = await client.put(f"{BASE}/connections/{connection_id}", headers=bearer(admin), json={"name": "SN"})
    assert renamed.json()["access"]["fields"] == fields, "a save that does not send them keeps them"
    stored = (await db.get(ConnectorNamedConnection, connection_id)).config
    assert stored["servicenow_api_style"] == "scripted" and stored["servicenow_changes_path"] == CHANGES_PATH

    result = (await client.post(f"{BASE}/connections/{connection_id}/test", headers=bearer(admin))).json()
    paths = [path for path, _params, _auth in instance.api_requests]
    assert result["state"] == "ok", result
    assert INCIDENTS_PATH in paths and CHANGES_PATH in paths and "/api/now/table/incident" not in paths
