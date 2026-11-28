"""Contract: the remaining Workspace gaps are closed and pinned."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.policy.coding_governance import router as coding_governance_router
from app.api.routes.secure_work.secure_work import router as secure_work_router
from app.api.routes.secure_work.secure_work_workflows import router as workflows_router
from app.db import get_db
from app.models import (
    Project,
    User,
    UserProject,
    WorkCodingPipelineConfig,
    WorkCodingPipelineRun,
    WorkItem,
)
from app.services.auth import get_current_user
from app.tools.jira_impl import _jira_helpers_api
from app.tools.jira_impl import _jira_query_ticket_actions as actions
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import DcJira, dc_config, dc_issue, use_transport, workspace_jira
from tests.services.knowledge.sources.test_jira_read_path_scope import _context
from tests.tools.jira_impl.test_jira_task_list_governance import _item, _operator

API = "/api/v1/secure-work"


@pytest.fixture
async def api(db):
    app = FastAPI()
    for router in (workflows_router, secure_work_router, coding_governance_router):
        app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://sw.test") as client:
        yield client, state


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _member_of_own(db) -> tuple[User, str]:
    own = Project(name=f"own-{uuid.uuid4().hex[:6]}", config={})
    db.add(own)
    await db.commit()
    operator = await _operator(db)
    db.add(UserProject(user_id=operator.id, project_id=own.id, role="admin"))
    await db.commit()
    return operator, own.id


async def test_c8c_workspace_bound_configs(api, client, auth_headers, db):
    api_client, state = api
    foreign = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one().id
    admin = await _admin(db)
    secret = WorkCodingPipelineConfig(name="secret-pipeline", project_id=foreign, created_by=admin.id)
    shared = WorkCodingPipelineConfig(name="global-pipeline", project_id=None, created_by=admin.id)
    db.add_all([secret, shared])
    await db.commit()
    operator, own = await _member_of_own(db)
    state["user"] = operator

    rows = {row["name"]: row for row in (await api_client.get(f"{API}/coding-pipelines")).json()["items"]}
    assert "secret-pipeline" not in rows and rows["global-pipeline"]["read_only"] is True
    for row, status in ((secret, 404), (shared, 403)):
        assert (await api_client.put(f"{API}/coding-pipelines/{row.id}", json={"name": "pwned"})).status_code == status
    assert (await api_client.post(f"{API}/coding-pipelines", json={"name": "x", "project_id": foreign})).status_code == 403
    assert (await api_client.post(f"{API}/coding-pipelines", json={"name": "no-ws"})).status_code == 403
    mine = await api_client.post(f"{API}/coding-pipelines", json={"name": "mine", "project_id": own})
    assert mine.status_code == 200, mine.text
    route = f"{API}/coding-pipelines/{mine.json()['id']}"
    assert (await api_client.put(route, json={"name": "mine", "project_id": foreign})).status_code == 403
    assert (await api_client.put(route, json={"name": "mine", "project_id": None})).status_code == 403
    kept = await api_client.put(route, json={"name": "renamed"})
    assert kept.status_code == 200 and kept.json()["project_id"] == own, "never silently cleared"


async def test_c1c_get_ticket_rechecks_what_jira_returned(monkeypatch):
    calls: list[dict] = []

    async def fake_get(client, jira_url, path, **kwargs):
        calls.append({"path": path, **kwargs})
        if path.endswith("/comment"):
            return {"comments": []}, "2"
        if path.endswith("BRD-2"):
            return {"key": "BRD-2", "fields": {"project": {"key": "BRD"}, "summary": "own",
                                               "parent": {"key": "SEC-1", "fields": {"summary": "secret epic"}}}}, "2"
        return {"key": "OPS-9", "fields": {"project": {"key": "OPS"}, "summary": "secret ops issue"}}, "2"

    monkeypatch.setattr(_jira_helpers_api, "_jira_api_get", fake_get)
    moved = await actions.GetJiraTicket().execute({"ticket_id": "BRD-1"}, _context(["BRD"]))
    assert "error" in moved and "OPS" in moved["error"] and "secret ops issue" not in str(moved)
    assert not [call for call in calls if call["path"].endswith("/comment")], "nothing more is read"
    assert "project" in calls[0]["params"]["fields"].split(",")
    own = await actions.GetJiraTicket().execute({"ticket_id": "BRD-2"}, _context(["BRD"]))
    assert own["summary"] == "own" and own["parent"] == {"external": True}


async def test_c1c_c1d_intake_parent_and_search_total(client, auth_headers, db, monkeypatch):
    issue = dc_issue("OCX-1")
    issue["fields"]["parent"] = {"key": "SEC-1", "fields": {"summary": "secret epic"}}
    jira = DcJira([issue])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    intake = (await create_jira_intake(db, {
        "name": "parent", "project_id": project_id, "filters": {"project_keys": ["OCX"]}}))["id"]
    await run_jira_intake(db, intake)
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-1"))).scalar_one()
    assert item.parent_key is None and "secret epic" not in str(item.source_fields_json)

    result = await SearchJiraTickets().execute({"jql": "status = Open"}, _context(["OCX"]))
    assert result["total"] is None, "Never Jira's total under an allowlist"


async def test_pinned_runs_are_scoped(api, db, monkeypatch):
    client, state = api
    use_transport(monkeypatch, DcJira([]).transport())
    foreign = await workspace_jira(db, dc_config(["OCX"]))
    admin = await _admin(db)
    item_id = await _item(db, foreign, "OCX-8")
    run = WorkCodingPipelineRun(work_item_id=item_id, started_by=admin.id)
    db.add(run)
    await db.commit()
    operator, own = await _member_of_own(db)
    state["user"] = operator

    assert (await client.post(f"{API}/coding-pipeline-runs/{run.id}/control", json={"action": "pause"})).status_code == 404
    assert (await client.put(f"{API}/coding-pipeline-runs/{run.id}/stages/intake", json={})).status_code == 404


async def test_each_layer_holds_on_its_own(api, db, monkeypatch):
    from fastapi import HTTPException

    from app.services.secure_work.jira.jira_sync_config import update_jira_sync_config

    client, state = api
    use_transport(monkeypatch, DcJira([]).transport())
    foreign = await workspace_jira(db, dc_config(["OCX"]))
    item_id = await _item(db, foreign, "OCX-9")
    operator, own = await _member_of_own(db)
    state["user"] = operator
    assert (await client.post(f"{API}/coding-pipelines/checks/preview", json={"work_item_id": item_id})).status_code == 404
    assert (await client.post(f"{API}/coding-pipelines/checks/preview", json={"project_id": foreign})).status_code == 403

    mine = await create_jira_intake(db, {"name": "mine", "project_id": own}, user=operator)
    with pytest.raises(HTTPException) as refused:
        await update_jira_sync_config(db, config_id=mine["id"], current_user=operator,
                                      payload={"project_id": foreign})
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "workspace_immutable"


async def test_c12_a_foreign_related_reference_answers_like_a_missing_one(api, db):
    from app.models import WorkItemChangeUnit, WorkRepositoryProfile
    from tests.support.workspace_resource_rows import seed_resource
    from tests.workspace_id_route_inventory import changed, snapshot

    client, state = api
    foreign = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one().id
    admin = await _admin(db)
    rows = {model: await seed_resource(db, model, workspace_id=foreign, user_id=admin.id, marker="c12-foreign")
            for model in (WorkItemChangeUnit, WorkRepositoryProfile)}
    await db.commit()
    operator, own = await _member_of_own(db)
    own_item = await _item(db, own, "OWN-12")
    state["user"] = operator
    cases = [
        ("POST", f"/work-items/{own_item}/reviewer-overrides", "json", {"selected_reviewer": "r"}, "change_unit_id",
         rows[WorkItemChangeUnit]),
    ]
    for method, path, slot, base, key, foreign_id in cases:
        before = await snapshot(db)
        answers = [await client.request(method, f"{API}{path}", **{slot: {**base, key: value}})
                   for value in (foreign_id, str(uuid.uuid4()))]
        assert changed(before, await snapshot(db)) == [], (path, key)
        assert answers[0].status_code == answers[1].status_code == 404, (path, key, answers[0].text)
        assert answers[0].json() == answers[1].json(), (path, key)
        assert "c12-foreign" not in answers[0].text
