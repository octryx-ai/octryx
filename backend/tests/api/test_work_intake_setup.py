"""Contract: setting up an intake: discovery, live count, draft save, and preview before enable."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.secure_work.secure_work_intake_setup import router
from app.db import get_db
from app.models import Scheduler, Task, User, WorkItem
from app.services.auth import get_current_user
from tests.jira_task_list_support import DcJira, dc_config, dc_issue, use_transport, workspace_jira
from tests.servicenow_intake_support import INCIDENTS_PATH, WritingStub, incident, stub, workspace

FIELDS = [{"id": "customfield_10020", "name": "Sprint", "schema": {"custom": "com.pyxis.greenhopper.jira:gh-sprint"}},
          {"id": "customfield_10016", "name": "Story point estimate", "schema": {}},
          {"id": "summary", "name": "Summary", "schema": {}}]


class DiscoveryJira(DcJira):
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/rest/api/2/project":
            return httpx.Response(200, json=[{"key": "CLM", "name": "Claims"}, {"key": "HR", "name": "People"}])
        if path == "/rest/api/2/issuetype":
            return httpx.Response(200, json=[{"name": "Bug"}, {"name": "Story"}, {"name": "Sub-task", "subtask": True}])
        if path == "/rest/api/2/status":
            return httpx.Response(200, json=[{"name": "To Do", "statusCategory": {"key": "new"}},
                                             {"name": "In Review", "statusCategory": {"key": "indeterminate"}}])
        if path == "/rest/api/2/field":
            return httpx.Response(200, json=FIELDS)
        return super().handler(request)


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://setup.test") as client:
        yield client, state


def _draft(**extra) -> dict:
    return {"source_type": "jira", "name": "Claims backlog", "connection_id": "default",
            "what": {"project_keys": ["CLM"], "issue_types": ["Bug", "Story"], "labels_exclude": ["human-only"]},
            "schedule": {"preset": "every_15_min"},
            "how": {"automation_mode": "needs_review", "automation_labels": ["octryx"],
                    "status_mapping": {"To Do": "ready_for_development"},
                    "field_mapping": {"sprint_field": "customfield_10020", "story_points_field": "customfield_10016"}},
            **extra}


async def test_discovery_and_count_stay_inside_the_connection(db, api, monkeypatch):
    client, state = api
    jira = DiscoveryJira([dc_issue("CLM-1"), dc_issue("CLM-2")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["CLM"]))
    state["user"] = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    base = f"/api/v1/secure-work/workspaces/{project_id}/intake"
    found = (await client.get(f"{base}/fields", params={"source_type": "jira", "connection_id": "default"})).json()
    assert found["projects"] == [{"key": "CLM", "name": "Claims"}]  # HR is outside the connection
    assert found["issue_types"] == ["Bug", "Story"]
    assert {s["name"]: s["state"] for s in found["statuses"]} == {"In Review": "review", "To Do": "intake"}
    roles = {role["role"]: role["field"] for role in found["fields"]}
    assert roles["sprint_field"] == {"id": "customfield_10020", "name": "Sprint"}
    assert roles["story_points_field"]["name"] == "Story point estimate" and roles["board_field"] is None
    counted = (await client.post(f"{base}/count", json={"source_type": "jira", "connection_id": "default",
                                                        "what": {"project_keys": ["CLM"]}})).json()
    assert counted["count"] == 2
    search = [r for r in jira.requests if r["path"] == "/rest/api/2/search"][-1]
    assert search["query"]["jql"][0].startswith('project in ("CLM")') or "CLM" in search["query"]["jql"][0]
    outside = (await client.post(f"{base}/count", json={"source_type": "jira", "connection_id": "default",
                                                        "what": {"project_keys": ["HR"]}})).json()
    assert outside == {"count": None, "reason": "query_refused"}
    unknown = await client.get(f"{base}/fields", params={"source_type": "jira", "connection_id": "nope"})
    assert unknown.status_code == 422


async def test_a_new_intake_is_enabled_only_after_a_preview_of_its_current_settings(db, api, monkeypatch):
    client, state = api
    jira = DiscoveryJira([dc_issue("CLM-7")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["CLM"]))
    state["user"] = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    base = f"/api/v1/secure-work/workspaces/{project_id}/intake"
    created = await client.post(base, json=_draft(what={"project_keys": ["CLM"]}))
    assert created.status_code == 200, created.text
    draft = created.json()
    assert draft["is_active"] is False and draft["schedule"] == {"preset": "every_15_min", "cron": None}
    assert draft["how"]["field_mapping"]["story_points_field"] == "customfield_10016"
    refused = await client.post(f"{base}/{draft['id']}/enable")
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "intake_preview_required"
    preview = (await client.post(f"{base}/{draft['id']}/preview")).json()
    summary = preview["sync_run"]["summary"]
    assert (summary["would_import"], summary["already_in_work"]) == (1, 0)
    assert summary["automation"] == {"labels": ["octryx"], "matching": 0, "mode": "needs_review"}
    assert (summary["pending_next_run"], summary["more_pending"]) == (None, False)
    assert preview["items"][0]["work_state"] == "intake"
    assert (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all() == []
    enabled = await client.post(f"{base}/{draft['id']}/enable")
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["intake"]["is_active"] is True
    assert enabled.json()["first_run"]["sync_run"]["summary"]["imported"] == 1
    task = next(t for t in (await db.execute(select(Task))).scalars() if (t.config or {}).get("sync_config_id") == draft["id"])
    scheduler = (await db.execute(select(Scheduler).where(Scheduler.task_id == task.id))).scalar_one()
    assert (scheduler.cron_expression, scheduler.is_active) == ("*/15 * * * *", True)
    disabled = (await client.post(f"{base}/{draft['id']}/disable")).json()
    assert disabled["is_active"] is False
    await client.put(f"{base}/{draft['id']}", json=_draft(name="Claims backlog v2"))
    again = await client.post(f"{base}/{draft['id']}/enable")
    assert again.status_code == 409, "an edit after the preview asks for a new one"


async def test_servicenow_uses_the_same_draft_and_flow(db, api, monkeypatch):
    client, state = api
    instance = WritingStub(incidents=0, changes=0)
    instance.data[INCIDENTS_PATH] = [incident(1, "New")]
    for _ in stub(monkeypatch, instance):
        project_id, admin = await workspace(db)
        state["user"] = admin
        base = f"/api/v1/secure-work/workspaces/{project_id}/intake"
        draft = {"source_type": "servicenow", "name": "Claims incidents", "connection_id": "default",
                 "what": {"tables": ["incident"], "excluded_states": ["Closed", "Resolved"]},
                 "schedule": {"preset": "hourly"}, "how": {"automation_mode": "human_only"}}
        created = await client.post(base, json=draft)
        assert created.status_code == 200, created.text
        saved = created.json()
        assert (saved["is_active"], saved["name"], saved["how"]["automation_mode"]) == (False, "Claims incidents", "human_only")
        assert (await client.post(base, json=draft)).status_code == 409  # one per Workspace
        preview = await client.post(f"{base}/{saved['id']}/preview")
        assert preview.status_code == 200 and preview.json()["summary"]["imported"] == 1
        enabled = (await client.post(f"{base}/{saved['id']}/enable")).json()
        assert enabled["intake"]["is_active"] is True and enabled["first_run"]["summary"]["imported"] == 1
        found = (await client.get(f"{base}/fields", params={"source_type": "servicenow", "connection_id": "default"})).json()
        assert found["tables"] == ["incident", "change_request"] and found["work_states"][0]["key"] == "intake"
