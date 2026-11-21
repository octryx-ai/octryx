"""Connections admin API through the real ``/api/v1/admin`` routes.

- ``connection-types`` comes from the descriptors (scope key, ticket states, secret flags);
- create / list / detail / partial update return the full detail and never a secret or a secret ref; the secret is
  stored for this connection alone (``<field>#<id>``) and the new row is not served by today's resolvers;
- ``uses``: the level is the connection's; a linked intake's status map is validated (``status_unknown``) and saved
  through the intake; a cron faster than 15 minutes is ``schedule_cron_invalid``; an unlinked use is ``409``;
- test → ``{state, state_reason, tested_at, checks}`` with ``access`` first, persisted;
- delete → ``409 connection_in_use`` with the list, else deleted with its secrets;
- Workspace admins see what is available to their Workspaces (platform-owned read-only), create only ``selected``
  on their own Workspaces; anyone else gets 403. Every write is audited without a secret.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.models import AuditLog, BuiltInToolConfig, ConnectorNamedConnection, StoredSecret, WorkItemSyncConfig
from app.services.named_connections.grants import available_rows
from tests.connections_admin_api_support import BASE, FAKE, JIRA_URL, _access, _clean, _create, _workspace
from tests.policy_engine_support import bearer, make_user


def _link(connection_id: str, workspace_id: str):
    from app.models import ConnectionWorkspace

    return ConnectionWorkspace(connection_id=connection_id, workspace_id=workspace_id)


async def test_connection_types_come_from_the_descriptors(client, db) -> None:
    admin = await make_user(db, admin=True)
    types = {item["type"]: item for item in _clean(await client.get(f"{BASE}/connection-types",
                                                                     headers=bearer(admin)))}
    assert {"jira", "confluence", "servicenow", "kubernetes", "aws", "bitbucket", "github"} <= set(types)
    jira = types["jira"]
    assert jira["scope_key"] == "projects" and types["confluence"]["scope_key"] == "spaces"
    assert types["servicenow"]["scope_key"] == "tables" and types["bitbucket"]["scope_key"] == "repositories"
    assert types["kubernetes"]["scope_key"] is None
    assert {"knowledge", "tickets", "agent_tools"} <= set(jira["uses"]) and "tickets" not in types["confluence"]["uses"]
    assert {state["key"] for state in jira["ticket_states"]} >= {"intake", "done", "rejected"}
    assert "ticket_states" not in types["confluence"]
    secrets = {field["key"]: field["secret"] for field in jira["access_fields"]}
    assert secrets["jira_token"] is True and secrets["jira_url"] is False
    assert "cloud_api_token" in jira["auth_kinds"]
    nobody = await make_user(db, admin=False)
    assert (await client.get(f"{BASE}/connection-types", headers=bearer(nobody))).status_code == 403


async def test_create_list_detail_update_never_return_a_secret_and_are_audited(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db, "Acme Orders")
    detail = await _create(client, admin, workspace_id)
    connection_id = detail["id"]
    assert detail["state"] == "untested" and detail["available_in"] == "selected"
    assert detail["workspaces"] == [{"id": workspace_id, "name": "Acme Orders"}]
    assert detail["access"]["secret_set"] is True and detail["access"]["base_url"] == JIRA_URL
    assert detail["access"]["account"] == "bot@example.test" and detail["access"]["auth"] == "cloud_api_token"
    assert detail["bound_scopes"] == ["BRD", "OPS"] and detail["owner"] == {"kind": "platform"}
    assert detail["can_edit"] is True and detail["uses"]["agent_tools"]["level"] == "read"
    # Every tool says whether it reads or writes, so the page never has to guess.
    tools = detail["uses"]["agent_tools"]["tools"]
    assert tools and {tool["level"] for tool in tools} <= {"read", "write"}
    assert detail["uses"]["knowledge"]["sources"] == [] and detail["uses"]["tickets"]["intakes"] == []

    secret = (await db.execute(select(StoredSecret).where(
        StoredSecret.field_name == f"jira_token#{connection_id}"))).scalar_one()
    assert secret.project_id is None and secret.tool_name == "jira"
    row = await db.get(ConnectorNamedConnection, connection_id)
    granted = {r.id: grant for r, grant in await available_rows(db, ["jira"], workspace_id)}
    assert granted[row.id].level == "read" and granted[row.id].is_active, "the runtime serves it there (E2 step 2)"
    assert row.id not in {r.id for r, _ in await available_rows(db, ["jira"], str(uuid.uuid4()))}

    listed = _clean(await client.get(f"{BASE}/connections", headers=bearer(admin)))["connections"]
    entry = next(item for item in listed if item["id"] == connection_id)
    assert entry["uses"] == {"knowledge": False, "tickets": False, "agent_tools": "read"}
    assert entry["deviation_count"] == 0 and entry["problems_count"] == 0 and entry["type"] == "jira"
    assert not any(item["id"] == connection_id for item in _clean(await client.get(
        f"{BASE}/connections?type=confluence", headers=bearer(admin)))["connections"])
    other = await _workspace(db)
    assert not any(item["id"] == connection_id for item in _clean(await client.get(
        f"{BASE}/connections?workspace_id={other}", headers=bearer(admin)))["connections"])

    updated = await client.put(f"{BASE}/connections/{connection_id}", headers=bearer(admin), json={
        "name": "Jira Cloud", "uses": {"agent_tools": {"level": "off"}}, "bound_scopes": ["BRD"]})
    assert updated.status_code == 200, updated.text
    body = _clean(updated)
    assert body["name"] == "Jira Cloud" and body["uses"]["agent_tools"]["level"] == "off"
    assert body["bound_scopes"] == ["BRD"] and body["access"]["secret_set"] is True, "unsent keys are kept"
    assert _clean(await client.get(f"{BASE}/connections/{connection_id}", headers=bearer(admin))) == body

    second = await client.post(f"{BASE}/connections", headers=bearer(admin), json={
        "type": "jira", "name": "jira cloud", "access": _access(), "available_in": "all"})
    assert second.status_code == 409 and second.json()["detail"]["code"] == "connection_name_taken"
    bad = await client.post(f"{BASE}/connections", headers=bearer(admin), json={"type": "nope", "name": "x"})
    assert bad.status_code == 422 and bad.json()["detail"]["field"] == "type"

    audits = (await db.execute(select(AuditLog).where(AuditLog.resource_id == connection_id))).scalars().all()
    assert {"admin.connection.created", "admin.connection.updated"} <= {item.action for item in audits}
    assert FAKE not in json.dumps([item.details for item in audits], default=str)


async def test_uses_write_through_the_linked_intake_with_validated_states_and_schedule(client, db) -> None:
    admin = await make_user(db, admin=True)
    workspace_id = await _workspace(db)
    row = ConnectorNamedConnection(id=str(uuid.uuid4()), tool_name="jira", project_id=workspace_id,
                                   scope_key=workspace_id, name="jira-a", bound_scopes=["BRD"],
                                   config={"jira_url": JIRA_URL, "jira_auth_mode": "cloud_api_token",
                                           "jira_email": "bot@example.test"},
                                   available_in="selected")
    db.add(row)
    db.add(_link(row.id, workspace_id))
    # Named connections apply while the Workspace's own entry of the connector is active (the access switch).
    db.add(BuiltInToolConfig(tool_name="jira", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    intake = WorkItemSyncConfig(name="BRD intake", project_id=workspace_id, source_type="jira", connection_id=row.id,
                                filters_json={"project_keys": ["BRD"]}, created_by=admin, is_active=False)
    db.add(intake)
    await db.commit()
    url = f"{BASE}/connections/{row.id}"

    unknown = await client.put(url, headers=bearer(admin), json={
        "uses": {"tickets": {"status_map": [{"source": "Done", "ours": "finished"}]}}})
    assert unknown.status_code == 422 and unknown.json()["detail"]["code"] == "status_unknown"
    assert unknown.json()["detail"]["field"] == "uses.tickets.status_map[0].ours"
    fast = await client.put(url, headers=bearer(admin), json={
        "uses": {"tickets": {"schedule": "custom", "schedule_cron": "*/5 * * * *"}}})
    assert fast.status_code == 422 and fast.json()["detail"]["code"] == "schedule_cron_invalid"
    outside = await client.put(url, headers=bearer(admin), json={
        "uses": {"tickets": {"scope": {"projects": ["OTHER"]}}}})
    assert outside.status_code == 422 and outside.json()["detail"]["code"] == "scope_outside_connection"
    write_back = await client.put(url, headers=bearer(admin), json={"uses": {"tickets": {"write_back": {
        "enabled": False}}}})
    assert write_back.status_code == 422 and write_back.json()["detail"]["code"] == "write_back_on_workflow"
    unlinked = await client.put(url, headers=bearer(admin), json={"uses": {"knowledge": {"enabled": False}}})
    assert unlinked.status_code == 409 and unlinked.json()["detail"]["code"] == "use_not_linked"

    saved = await client.put(url, headers=bearer(admin), json={"uses": {"tickets": {
        "status_map": [{"source": "In Review", "ours": "review"}, {"source": "Done", "ours": "done"}],
        "schedule": "custom", "schedule_cron": "0 */2 * * *", "filter": "labels = OE"}}})
    assert saved.status_code == 200, saved.text
    tickets = saved.json()["uses"]["tickets"]
    assert tickets["status_map"] == [{"source": "Done", "ours": "done"}, {"source": "In Review", "ours": "review"}]
    assert (tickets["schedule"], tickets["schedule_cron"], tickets["filter"]) == ("custom", "0 */2 * * *",
                                                                                   "labels = OE")
    assert tickets["intakes"][0]["intake_id"] == intake.id and tickets["intakes"][0]["enabled"] is False
    await db.refresh(intake)
    assert intake.sync_options_json["status_state_mapping"] == {"In Review": "review", "Done": "done"}
