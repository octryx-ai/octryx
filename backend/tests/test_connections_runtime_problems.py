"""E2 step 2: problems, the connection page's problems and who may test a connection.

- an unlinked Knowledge source or intake (``connection_id`` NULL, or ``default`` for an intake) is a ``connection``
  problem ``connection_unlinked`` (attention) whose fix opens the connections page;
- a failing connection is a problem whose fix opens ``/chat?area=admin&tab=adminConnections&connection=<uuid>``;
  the connection list and detail count the problems about it (``problems_count``, ``problems``);
- ``POST …/test``: a Workspace admin who sees a connection may test it even without edit rights; members and
  outsiders may not.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.api.routes import connections_admin as routes
from app.models import (
    ConnectionWorkspace,
    ConnectorNamedConnection,
    KnowledgeSourceConnector,
    Project,
    User,
    UserProject,
    WorkItemSyncConfig,
)
from app.services.problems import connections as connection_problems
from app.services.problems.links import TARGET_CONNECTION, fix_link
from app.services.problems.model import CollectContext
from app.time_utils import utc_now
from tests.policy_engine_support import bearer, make_user

BASE = "/api/v1/admin"
URL = "https://jira.example.test"


async def _workspace(db) -> str:
    project = Project(id=str(uuid.uuid4()), name=f"ws-{uuid.uuid4().hex[:6]}", is_active=True)
    db.add(project)
    await db.flush()
    return project.id


async def _connection(db, workspace_id: str, *, state: str = "untested", reason: str | None = None) -> str:
    row = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="jira", project_id=None, scope_key="global",
        name=f"jira-{uuid.uuid4().hex[:6]}", bound_scopes=["OPS"], config={"jira_url": URL},
        available_in="selected", state=state, state_reason=reason, owner_kind="workspace",
        owner_workspace_id=workspace_id,
    )
    db.add(row)
    await db.flush()
    db.add(ConnectionWorkspace(connection_id=row.id, workspace_id=workspace_id))
    await db.flush()
    return row.id


async def _admin_id(db) -> str:
    return (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()


def test_the_connection_link_opens_the_connection_page() -> None:
    assert fix_link(TARGET_CONNECTION, object_id="c-1", workspace_id="w")["href"] == (
        "/chat?area=admin&tab=adminConnections&connection=c-1")
    assert fix_link(TARGET_CONNECTION)["href"] == "/chat?area=admin&tab=adminConnections"


async def test_unlinked_uses_and_failing_connections_are_connection_problems(db) -> None:
    ws_a = await _workspace(db)
    failing = await _connection(db, ws_a, state="failing", reason="Sign-in failed.")
    linked = KnowledgeSourceConnector(project_id=ws_a, connector_key="linked", kind="jira", scope={},
                                      connection_id=failing)
    unlinked = KnowledgeSourceConnector(project_id=ws_a, connector_key="legacy", kind="jira", scope={})
    git = KnowledgeSourceConnector(project_id=ws_a, connector_key="repo", kind="git_repository", scope={})
    admin = await _admin_id(db)
    defaulted = WorkItemSyncConfig(name="Ops", project_id=ws_a, source_type="jira", connection_id="default",
                                   created_by=admin)
    named = WorkItemSyncConfig(name="Named", project_id=ws_a, source_type="jira", connection_id=failing,
                               created_by=admin)
    db.add_all([linked, unlinked, git, defaulted, named])
    await db.flush()

    problems = await connection_problems.collect(db, CollectContext(now=utc_now(), workspace_ids=frozenset({ws_a})))
    by_object = {item.object_id: item for item in problems}
    assert set(by_object) == {failing, unlinked.id, defaulted.id}, "linked uses and a git source are not unlinked"
    for item in (by_object[unlinked.id], by_object[defaulted.id]):
        assert (item.kind, item.severity, item.reason_code) == ("connection", "attention", "connection_unlinked")
        assert item.fix["href"] == "/chat?area=admin&tab=adminConnections"
    state = by_object[failing]
    assert (state.severity, state.reason_code, state.connection_id) == ("problem", "connection_failing", failing)
    assert state.title.endswith("Sign-in failed.") and state.workspace_id == ws_a
    assert state.fix["href"] == f"/chat?area=admin&tab=adminConnections&connection={failing}"
    other = await connection_problems.collect(db, CollectContext(now=utc_now(), workspace_ids=frozenset({"x"})))
    assert not other, "scoped to the Workspaces in view"


async def test_the_connection_views_count_the_aggregators_problems(client, db) -> None:
    ws_a = await _workspace(db)
    failing = await _connection(db, ws_a, state="failing", reason="Sign-in failed.")
    healthy = await _connection(db, ws_a)
    await db.commit()
    admin = await make_user(db, admin=True)
    listed = (await client.get(f"{BASE}/connections", headers=bearer(admin))).json()["connections"]
    counts = {item["id"]: item["problems_count"] for item in listed}
    assert counts[failing] == 1 and counts[healthy] == 0
    detail = (await client.get(f"{BASE}/connections/{failing}", headers=bearer(admin))).json()
    assert detail["problems_count"] == 1 and detail["problems"][0]["fix"]["href"].endswith(f"connection={failing}")


async def test_a_workspace_admin_who_sees_a_connection_may_test_it(client, db, monkeypatch) -> None:
    ws_a, ws_b = await _workspace(db), await _workspace(db)
    platform = ConnectorNamedConnection(
        id=str(uuid.uuid4()), tool_name="jira", project_id=None, scope_key="global", name="platform-jira",
        bound_scopes=[], config={"jira_url": URL, "jira_auth_mode": "bearer_pat"}, available_in="selected",
    )
    db.add(platform)
    await db.flush()
    db.add(ConnectionWorkspace(connection_id=platform.id, workspace_id=ws_a))
    ws_admin, outsider, member = [await make_user(db, admin=False) for _ in range(3)]
    db.add_all([UserProject(user_id=ws_admin, project_id=ws_a, role="admin"),
                UserProject(user_id=outsider, project_id=ws_b, role="admin"),
                UserProject(user_id=member, project_id=ws_a, role="member")])
    await db.commit()

    async def fake_test(tool_name, config, *, db=None, scope_check=False):
        return {"ok": True, "summary": "Signed in."}

    monkeypatch.setattr(routes, "run_connector_connection_test", fake_test)
    url = f"{BASE}/connections/{platform.id}"
    detail = (await client.get(url, headers=bearer(ws_admin))).json()
    assert detail["can_edit"] is False
    tested = await client.post(f"{url}/test", headers=bearer(ws_admin))
    assert tested.status_code == 200 and tested.json()["state"] == "ok"
    assert (await client.put(url, json={"name": "x"}, headers=bearer(ws_admin))).status_code == 403
    assert (await client.post(f"{url}/test", headers=bearer(outsider))).status_code == 404
    assert (await client.post(f"{url}/test", headers=bearer(member))).status_code == 403
