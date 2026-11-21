"""Connector watchers, watcher rules and the Work-role catalogs are bound to the caller's Workspaces.

A non-admin Work operator (platform role ``operation``) manages the watchers and rules of the Workspaces they are a
member of; a platform admin every one. A named Workspace the caller is no member of answers exactly like an unknown
one (404 ``project_not_found``), and a watcher, event, rule, function or role of such a Workspace exactly like a
missing one: nothing of it is read, written or confirmed.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import ConnectorWatcher, ConnectorWatcherRule, Role, UserRole
from app.models.runtime.work_role_model import WorkRole, WorkRoleFunction
from tests.connector_watchers_support import _create_rule, _create_watcher, _watcher_payload
from tests.knowledge_evidence_seed_support import seed_member, seed_workspace
from tests.policy_engine_support import bearer
from tests.workspace_id_route_inventory import changed, snapshot

pytestmark = pytest.mark.asyncio

MARKER = "foreign-catalog-marker"


async def _operator(db, workspace_id: str) -> str:
    user_id = await seed_member(db, workspace_id=workspace_id, role="member")
    role = (await db.execute(select(Role).where(Role.name == "operation"))).scalar_one_or_none()
    if role is None:
        role = Role(name="operation", description="operation")
        db.add(role)
        await db.flush()
    db.add(UserRole(user_id=user_id, role_id=role.id))
    await db.flush()
    return user_id


def _answer(response) -> tuple[int, str]:
    body = response.json()
    if isinstance(body, dict):
        body.pop("request_id", None)
    return response.status_code, repr(body)


async def _same_for_foreign_and_unknown(client, db, caller: str, method: str, foreign_url: str, unknown_url: str,
                                        **kwargs) -> tuple[int, str]:
    before = await snapshot(db)
    foreign = await client.request(method, foreign_url, headers=bearer(caller), **kwargs)
    unknown = await client.request(method, unknown_url, headers=bearer(caller), **kwargs)
    db.expire_all()
    assert changed(before, await snapshot(db)) == [], f"{method} {foreign_url} wrote"
    assert MARKER not in foreign.text, foreign.text[:300]
    assert _answer(foreign) == _answer(unknown), (foreign.text[:300], unknown.text[:300])
    return _answer(foreign)


async def test_a_work_operator_reaches_only_the_watchers_and_rules_of_their_workspaces(client, db, auth_headers):
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    operator = await _operator(db, mine)
    await db.commit()
    foreign_watcher = await _create_watcher(client, auth_headers, project_id=foreign, name=MARKER)
    global_watcher = await _create_watcher(client, auth_headers, name=f"{MARKER}-global")
    foreign_rule = await _create_rule(client, auth_headers, project_id=foreign, name=MARKER)
    own_watcher = await _create_watcher(client, bearer(operator), project_id=mine, name="own watcher")
    own_rule = await _create_rule(client, bearer(operator), project_id=mine, name="own rule")
    unknown = str(uuid.uuid4())

    # Lists: the caller's Workspaces only; a named foreign Workspace is the 404 of an unknown one.
    for path in ("/api/v1/connector-watchers", "/api/v1/connector-watchers/rules"):
        listed = await client.get(path, params={"include_inactive": True}, headers=bearer(operator))
        assert listed.status_code == 200 and MARKER not in listed.text, listed.text[:300]
        status, _body = await _same_for_foreign_and_unknown(
            client, db, operator, "GET", f"{path}?project_id={foreign}", f"{path}?project_id={unknown}")
        assert status == 404
    listed = await client.get("/api/v1/connector-watchers", params={"project_id": mine}, headers=bearer(operator))
    assert [item["id"] for item in listed.json()["items"]] == [own_watcher["id"]]
    for path in ("/api/v1/connector-watchers/events", "/api/v1/connector-watchers/rule-decisions"):
        assert MARKER not in (await client.get(path, headers=bearer(operator))).text

    # Writes into a foreign Workspace: the 404 of an unknown one, nothing written.
    for path, payload in (("/api/v1/connector-watchers", _watcher_payload()),
                          ("/api/v1/connector-watchers/rules", {"name": "rule"})):
        before = await snapshot(db)
        answers = [await client.post(path, headers=bearer(operator), json={**payload, "project_id": workspace})
                   for workspace in (foreign, unknown)]
        db.expire_all()
        assert changed(before, await snapshot(db)) == [], path
        assert _answer(answers[0]) == _answer(answers[1]) and answers[0].status_code == 404
        own_id = own_rule["id"] if path.endswith("rules") else own_watcher["id"]
        moved = await client.put(f"{path}/{own_id}", headers=bearer(operator), json={**payload, "project_id": foreign})
        assert moved.status_code == 404, moved.text

    # A record of a foreign Workspace, and a global one, by id: the 404 of a missing record.
    event = await client.post(f"/api/v1/connector-watchers/{foreign_watcher['id']}/webhook",
                              headers={"X-Watcher-Secret": "test-secret"},
                              json={"event_type": "jira.issue.updated", "external_id": "OCX-1", "actor": MARKER})
    assert event.status_code == 200, event.text
    cases = [
        ("PUT", "/api/v1/connector-watchers/{}", foreign_watcher["id"], {"json": _watcher_payload(project_id=mine)}),
        ("PUT", "/api/v1/connector-watchers/{}", global_watcher["id"], {"json": _watcher_payload(project_id=mine)}),
        ("POST", "/api/v1/connector-watchers/{}/poll", foreign_watcher["id"], {"json": {"events": [{"id": "e"}]}}),
        ("PUT", "/api/v1/connector-watchers/rules/{}", foreign_rule["id"],
         {"json": {"name": "taken", "project_id": mine}}),
        ("POST", "/api/v1/connector-watchers/rules/{}/test", foreign_rule["id"], {"json": {"actor": "alice"}}),
        ("POST", "/api/v1/connector-watchers/events/{}/retry", event.json()["id"], {}),
        ("POST", "/api/v1/connector-watchers/events/{}/replay", event.json()["id"], {}),
    ]
    for method, template, record_id, kwargs in cases:
        status, _body = await _same_for_foreign_and_unknown(
            client, db, operator, method, template.format(record_id), template.format(uuid.uuid4().hex), **kwargs)
        assert status == 404, (method, template)
    assert (await db.get(ConnectorWatcher, foreign_watcher["id"])).name == MARKER
    assert (await db.get(ConnectorWatcherRule, foreign_rule["id"])).project_id == foreign

    # A platform admin keeps every Workspace and the global records.
    listed = await client.get("/api/v1/connector-watchers", params={"project_id": foreign}, headers=auth_headers)
    assert {item["id"] for item in listed.json()["items"]} >= {foreign_watcher["id"], global_watcher["id"]}


async def test_the_work_role_catalogs_answer_a_foreign_workspace_like_an_unknown_one(client, db, auth_headers):
    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="member")
    function = WorkRoleFunction(key="foreign_fn", name=MARKER, description="", project_id=foreign, scope_key=foreign,
                                tools_json=[f"{MARKER}_tool"], created_by=member, updated_by=member)
    role = WorkRole(key="foreign_role", name=MARKER, description="", project_id=foreign, scope_key=foreign,
                    trusted=False, created_by=member, updated_by=member)
    db.add_all([function, role])
    await db.commit()
    function_id, role_id = function.id, role.id
    unknown = str(uuid.uuid4())

    for path in ("/api/v1/work-roles/functions", "/api/v1/work-roles/roles"):
        status, _body = await _same_for_foreign_and_unknown(
            client, db, member, "GET", f"{path}?workspace_id={foreign}", f"{path}?workspace_id={unknown}")
        assert status == 404
        assert MARKER not in (await client.get(path, headers=bearer(member))).text
        own = await client.get(path, params={"workspace_id": mine}, headers=bearer(member))
        assert own.status_code == 200 and MARKER not in own.text

    missing = uuid.uuid4().hex
    for method, path, kwargs in (
        ("GET", "/api/v1/work-roles/roles/{}", {}),
        ("PATCH", "/api/v1/work-roles/roles/{}", {"json": {"expected_version": 1, "name": "taken"}}),
        ("PUT", "/api/v1/work-roles/roles/{}/trusted", {"json": {"expected_version": 1, "trusted": True, "reason": "x"}}),
        ("DELETE", "/api/v1/work-roles/roles/{}", {}),
    ):
        status, _body = await _same_for_foreign_and_unknown(
            client, db, member, method, path.format(role_id), path.format(missing), **kwargs)
        assert status == 404, path
    for method, path, kwargs in (
        ("PATCH", "/api/v1/work-roles/functions/{}", {"json": {"expected_version": 1, "name": "taken"}}),
        ("PUT", "/api/v1/work-roles/functions/{}/tools", {"json": {"expected_tools_version": 1, "tools": []}}),
        ("DELETE", "/api/v1/work-roles/functions/{}", {}),
    ):
        status, _body = await _same_for_foreign_and_unknown(
            client, db, member, method, path.format(function_id), path.format(missing), **kwargs)
        assert status == 404, path
    status, _body = await _same_for_foreign_and_unknown(
        client, db, member, "GET", f"/api/v1/work-roles/tool-catalog?function_id={function_id}",
        f"/api/v1/work-roles/tool-catalog?function_id={missing}")
    assert status == 404

    # A platform admin reads the foreign Workspace's catalog.
    listed = await client.get("/api/v1/work-roles/roles", params={"workspace_id": foreign}, headers=auth_headers)
    assert listed.status_code == 200 and role_id in {item["id"] for item in listed.json()["roles"]}


async def test_global_catalog_rows_never_carry_a_foreign_workspaces_related_rows(client, db, auth_headers):
    """A global function used by a foreign Workspace's role, a global role assigned there, a foreign function sharing
    a global key and a connection available only there: none of it reaches an outsider through a catalog view."""
    from app.models.runtime.named_connection import ConnectorNamedConnection
    from app.models.runtime.work_role_model import GLOBAL_SCOPE, WorkRoleAssignment, WorkRoleFunctionLink

    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="admin")
    foreign_admin = await seed_member(db, workspace_id=foreign, role="admin")
    shared = WorkRoleFunction(key="shared_catalog_fn", name="Shared", description="", project_id=None,
                              scope_key=GLOBAL_SCOPE, tools_json=[], created_by=member, updated_by=member)
    twin = WorkRoleFunction(key="shared_catalog_fn", name=MARKER, description="", project_id=foreign,
                            scope_key=foreign, tools_json=[], created_by=member, updated_by=member)
    linked = WorkRoleFunction(key="linked_catalog_fn", name="Linked", description="", project_id=None,
                              scope_key=GLOBAL_SCOPE, tools_json=[], created_by=member, updated_by=member)
    connection = ConnectorNamedConnection(tool_name="jira", project_id=foreign, scope_key=foreign, name=MARKER,
                                          available_in="selected", config={})
    global_role = WorkRole(key="global_catalog_role", name="Global", description="", project_id=None,
                           scope_key=GLOBAL_SCOPE, trusted=False, created_by=member, updated_by=member)
    db.add_all([shared, linked, twin, connection, global_role])
    await db.flush()
    global_role.connection_ids_json = [connection.id]
    db.add(WorkRoleFunctionLink(role_id=global_role.id, function_id=shared.id))
    db.add(WorkRoleAssignment(project_id=foreign, role_id=global_role.id, subject_kind="user", user_id=foreign_admin,
                              subject_key=foreign_admin))
    await db.commit()
    created = await client.post("/api/v1/work-roles/roles", headers=bearer(foreign_admin), json={
        "workspace_id": foreign, "key": "foreign_catalog_key", "name": MARKER, "function_keys": ["linked_catalog_fn"]})
    assert created.status_code == 201, created.text

    def role_keys(response, function: WorkRoleFunction) -> list[str]:
        assert response.status_code == 200, response.text
        return next(item for item in response.json()["functions"] if item["id"] == function.id)["role_keys"]

    for params in ({}, {"workspace_id": mine}):
        listed = await client.get("/api/v1/work-roles/functions", params=params, headers=bearer(member))
        assert "foreign_catalog_key" not in listed.text and MARKER not in listed.text, listed.text[:300]
        assert role_keys(listed, shared) == ["global_catalog_role"] and role_keys(listed, linked) == []
        roles = await client.get("/api/v1/work-roles/roles", params=params, headers=bearer(member))
        assert roles.status_code == 200 and MARKER not in roles.text, roles.text[:300]
        view = next(item for item in roles.json()["roles"] if item["id"] == global_role.id)
        assert view["functions"] == [{"key": "shared_catalog_fn", "name": "Shared"}]
        assert view["assignment_count"] == 0
        assert view["connections"] == [] and view["connection_ids"] == []
    page = await client.get(f"/api/v1/work-roles/workspaces/{mine}", headers=bearer(member))
    assert page.status_code == 200 and MARKER not in page.text and "foreign_catalog_key" not in page.text

    # A foreign connection is the 422 of an unknown one when the caller names it on their own role.
    answers = [await client.post("/api/v1/work-roles/roles", headers=bearer(member), json={
        "workspace_id": mine, "key": "own_role", "name": "Own", "delivery_connections": "selected",
        "connection_ids": [connection_id]}) for connection_id in (connection.id,)]
    unknown = await client.post("/api/v1/work-roles/roles", headers=bearer(member), json={
        "workspace_id": mine, "key": "own_role", "name": "Own", "delivery_connections": "selected",
        "connection_ids": [str(uuid.uuid4())]})
    assert answers[0].status_code == unknown.status_code == 422
    assert answers[0].json()["detail"]["code"] == unknown.json()["detail"]["code"] == "unknown_connection"

    # The foreign Workspace's admin and a platform admin see the foreign link and assignment.
    theirs = await client.get("/api/v1/work-roles/functions", params={"workspace_id": foreign},
                              headers=bearer(foreign_admin))
    assert role_keys(theirs, linked) == ["foreign_catalog_key"]
    admin = await client.get("/api/v1/work-roles/functions", headers=auth_headers)
    assert role_keys(admin, linked) == ["foreign_catalog_key"]
    roles = await client.get("/api/v1/work-roles/roles", headers=auth_headers)
    view = next(item for item in roles.json()["roles"] if item["id"] == global_role.id)
    assert view["assignment_count"] == 1 and view["connections"][0]["name"] == f"{MARKER} (jira)"


async def test_a_global_roles_connection_follows_visibility_and_availability(client, db, auth_headers):
    """Ids and names of a global role's connection reach a view together or not at all: the catalog shows those the
    caller sees, a view addressed to one Workspace (its role listing, the effective permission there) only those
    available in that Workspace, and an availability change shows or hides the stored link."""
    from app.models import ConnectionWorkspace
    from app.models.runtime.named_connection import ConnectorNamedConnection
    from app.models.runtime.work_role_model import (
        DELIVERY_SELECTED,
        GLOBAL_SCOPE,
        WorkRoleAssignment,
        WorkspaceWorkRoleSettings,
    )

    mine, foreign = await seed_workspace(db), await seed_workspace(db)
    member = await seed_member(db, workspace_id=mine, role="admin")
    connection = ConnectorNamedConnection(tool_name="jira", project_id=foreign, scope_key=foreign, name=MARKER,
                                          available_in="selected", config={})
    role = WorkRole(key="global_delivery_role", name="Delivery", description="", project_id=None,
                    scope_key=GLOBAL_SCOPE, trusted=False, delivery_connections=DELIVERY_SELECTED,
                    created_by=member, updated_by=member)
    db.add_all([connection, role])
    await db.flush()
    role.connection_ids_json = [connection.id]
    db.add_all([WorkRoleAssignment(project_id=mine, role_id=role.id, subject_kind="user", user_id=member,
                                   subject_key=member),
                WorkspaceWorkRoleSettings(project_id=mine, role_based_tools=True, version=1)])
    await db.commit()
    shown = {"id": connection.id, "name": f"{MARKER} (jira)"}

    async def views(headers) -> list[tuple[list, list]]:
        found = []
        for params in ({}, {"workspace_id": mine}):
            listed = await client.get("/api/v1/work-roles/roles", params=params, headers=headers)
            assert listed.status_code == 200, listed.text
            item = next(row for row in listed.json()["roles"] if row["id"] == role.id)
            assert [entry["id"] for entry in item["connections"]] == item["connection_ids"]
            found.append((item["connection_ids"], item["connections"]))
        return found

    async def effective() -> tuple[list, list]:
        answer = await client.get(f"/api/v1/work-roles/workspaces/{mine}/me", headers=bearer(member))
        assert answer.status_code == 200, answer.text
        body = answer.json()
        assert [entry["id"] for entry in body["write_connections_detail"]] == body["write_connections"]
        return body["write_connections"], body["write_connections_detail"]

    # Available only in the foreign Workspace: the outsider sees neither id nor name anywhere; a platform admin sees
    # it in the global catalog, not in a view addressed to a Workspace where it is unavailable.
    assert await views(bearer(member)) == [([], []), ([], [])]
    assert await effective() == ([], [])
    page = await client.get(f"/api/v1/work-roles/workspaces/{mine}", headers=bearer(member))
    assert page.status_code == 200 and connection.id not in page.text and MARKER not in page.text
    assert await views(auth_headers) == [([connection.id], [shown]), ([], [])]

    # Made available in the caller's Workspace: the same stored link appears with its name in every view.
    db.add(ConnectionWorkspace(connection_id=connection.id, workspace_id=mine))
    await db.commit()
    assert await views(bearer(member)) == [([connection.id], [shown])] * 2
    assert await effective() == ([connection.id], [shown])

    # Unshared again: the link disappears from the views and stays stored.
    await db.delete(await db.get(ConnectionWorkspace, (connection.id, mine)))
    await db.commit()
    assert await views(bearer(member)) == [([], []), ([], [])]
    assert await effective() == ([], [])
    role_id, connection_id = role.id, connection.id
    db.expire_all()
    assert (await db.get(WorkRole, role_id)).connection_ids_json == [connection_id]
