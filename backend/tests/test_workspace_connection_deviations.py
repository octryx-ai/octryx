"""A Workspace's connections and its deviations (E2 1.3) through ``/api/v1/workspaces/{ws}/connections``.

- the list is ``{connections: [...]}`` with only what is available in the Workspace, each with ``effective``,
  ``deviation`` and ``can_edit`` (Workspace admin/owner or platform admin);
- a deviation is stored only when narrower (``422 deviation_not_narrower`` with ``field``), returns
  ``{effective, deviation}``, shows in the connection detail (``deviations[].can_edit``) and resets to ``null``;
- members read, Workspace admins set and reset, any other member gets 403; a caller who is no member gets the 404
  of an unknown Workspace; a connection not available here is 404.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import AuditLog, KnowledgeSourceConnector, Project, UserProject
from tests.policy_engine_support import bearer, make_user

ADMIN = "/api/v1/admin/connections"
FAKE = "fake-confluence-token-77"


async def _workspace(db, name: str) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"{name}-{uuid.uuid4().hex[:4]}", is_active=True)
    db.add(project)
    await db.commit()
    return project.id


async def _member(db, workspace_id: str, role: str) -> str:
    user_id = await make_user(db, admin=False)
    db.add(UserProject(user_id=user_id, project_id=workspace_id, role=role))
    await db.commit()
    return user_id


async def _connection(client, admin: str, workspaces: list[str]) -> str:
    created = await client.post(ADMIN, headers=bearer(admin), json={
        "type": "confluence", "name": f"Wiki {uuid.uuid4().hex[:4]}", "available_in": "selected",
        "workspaces": workspaces, "bound_scopes": ["SALES", "OPS"],
        "access": {"confluence_url": "https://wiki.example.test/wiki", "confluence_auth_mode": "bearer_pat",
                   "confluence_token": FAKE}})
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _url(workspace_id: str, connection_id: str | None = None) -> str:
    base = f"/api/v1/workspaces/{workspace_id}/connections"
    return f"{base}/{connection_id}/deviation" if connection_id else base


async def test_the_workspace_list_shows_available_connections_with_effective_values(client, db) -> None:
    admin = await make_user(db, admin=True)
    here, elsewhere = await _workspace(db, "here"), await _workspace(db, "elsewhere")
    mine = await _connection(client, admin, [here])
    other = await _connection(client, admin, [elsewhere])
    db.add(KnowledgeSourceConnector(project_id=here, connector_key="sales-wiki", kind="confluence",
                                    scope={"spaces": ["SALES", "OPS"]}, connection_id=mine, schedule_enabled=True,
                                    schedule_interval_minutes=60))
    await db.commit()
    member = await _member(db, here, "member")

    listed = await client.get(_url(here), headers=bearer(member))
    assert listed.status_code == 200 and FAKE not in listed.text
    rows = {row["id"]: row for row in listed.json()["connections"]}
    assert mine in rows and other not in rows
    row = rows[mine]
    assert row["type"] == "confluence" and row["state"] == "untested" and row["deviation"] is None
    assert row["can_edit"] is False, "a member reads only"
    assert row["effective"]["knowledge"] == {"enabled": True, "scope": {"spaces": ["SALES", "OPS"]},
                                             "schedule": "hourly", "schedule_cron": None}
    assert row["effective"]["agent_tools"] == {"level": "read"}
    ws_admin = await _member(db, here, "admin")
    assert all(item["can_edit"] for item in (await client.get(_url(here), headers=bearer(ws_admin))).json()[
        "connections"])
    outsider = await make_user(db, admin=False)
    assert (await client.get(_url(here), headers=bearer(outsider))).status_code == 404  # an unknown Workspace's


async def test_a_workspace_admin_sets_a_narrower_deviation_and_resets_it(client, db) -> None:
    admin = await make_user(db, admin=True)
    here = await _workspace(db, "here")
    connection_id = await _connection(client, admin, [here])
    db.add(KnowledgeSourceConnector(project_id=here, connector_key="sales-wiki", kind="confluence",
                                    scope={"spaces": ["SALES", "OPS"]}, connection_id=connection_id,
                                    schedule_enabled=True, schedule_interval_minutes=60))
    await db.commit()
    ws_admin, member = await _member(db, here, "admin"), await _member(db, here, "member")
    deviation = {"knowledge": {"scope": {"spaces": ["sales"]}, "schedule": "off"}, "agent_tools": {"level": "off"}}

    assert (await client.put(_url(here, connection_id), json=deviation, headers=bearer(member))).status_code == 403
    wider = await client.put(_url(here, connection_id), headers=bearer(ws_admin),
                             json={"knowledge": {"scope": {"spaces": ["SALES", "NEW"]}}})
    assert wider.status_code == 422
    assert wider.json()["detail"] == {"code": "deviation_not_narrower", "field": "knowledge.scope.spaces",
                                      "message": wider.json()["detail"]["message"]}
    level = await client.put(_url(here, connection_id), headers=bearer(ws_admin),
                             json={"agent_tools": {"level": "write"}})
    assert level.status_code == 422 and level.json()["detail"]["field"] == "agent_tools.level"
    wrong_key = await client.put(_url(here, connection_id), headers=bearer(ws_admin),
                                 json={"knowledge": {"scope": {"projects": ["SALES"]}}})
    assert wrong_key.status_code == 422 and wrong_key.json()["detail"]["field"] == "knowledge.scope"

    saved = await client.put(_url(here, connection_id), json=deviation, headers=bearer(ws_admin))
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["deviation"] == {"knowledge": {"scope": {"spaces": ["SALES"]}, "schedule": "off"},
                                 "agent_tools": {"level": "off"}}
    assert body["effective"]["knowledge"]["scope"] == {"spaces": ["SALES"]}
    assert body["effective"]["knowledge"]["schedule"] == "manual"
    assert body["effective"]["agent_tools"]["level"] == "off"
    # The widest the Workspace may use stays visible, so the narrowing page can offer every space again.
    assert body["base"]["knowledge"]["scope"] == {"spaces": ["SALES", "OPS"]}
    assert body["base"]["agent_tools"] == {"level": "read"}

    detail = (await client.get(f"{ADMIN}/{connection_id}", headers=bearer(admin))).json()
    assert detail["deviations"][0]["workspace"]["id"] == here and detail["deviations"][0]["can_edit"] is True
    assert detail["deviations"][0]["fields"] == body["deviation"]
    listed = (await client.get(f"{ADMIN}", headers=bearer(admin))).json()["connections"]
    assert next(item for item in listed if item["id"] == connection_id)["deviation_count"] == 1
    other = await _workspace(db, "other")
    other_admin = await _member(db, other, "admin")
    assert (await client.delete(_url(here, connection_id), headers=bearer(other_admin))).status_code == 404

    reset = await client.delete(_url(here, connection_id), headers=bearer(ws_admin))
    assert reset.status_code == 200 and reset.json()["deviation"] is None
    assert reset.json()["effective"]["knowledge"]["scope"] == {"spaces": ["SALES", "OPS"]}
    actions = {row.action for row in (await db.execute(select(AuditLog).where(
        AuditLog.resource_id == f"{connection_id}:{here}"))).scalars()}
    assert actions == {"admin.connection.deviation_set", "admin.connection.deviation_reset"}


async def test_a_connection_not_available_in_the_workspace_has_no_deviation(client, db) -> None:
    admin = await make_user(db, admin=True)
    here, elsewhere = await _workspace(db, "here"), await _workspace(db, "elsewhere")
    connection_id = await _connection(client, admin, [elsewhere])
    refused = await client.put(_url(here, connection_id), headers=bearer(admin),
                               json={"agent_tools": {"level": "off"}})
    assert refused.status_code == 404
    no_workspace = await client.get(_url("missing-workspace"), headers=bearer(admin))
    assert no_workspace.status_code == 404
