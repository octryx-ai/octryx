"""Contract: the per-Workspace intake overview and run history."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.routes.secure_work.secure_work_intake import router
from app.db import get_db
from app.models import (
    BuiltInToolConfig,
    ConnectorNamedConnection,
    Project,
    User,
    UserProject,
    WorkItem,
    WorkItemSyncConfig,
    WorkItemSyncRun,
)
from app.models.project.knowledge_source_sync import KnowledgeSourceConnector, KnowledgeSourceSyncRun
from app.services.auth import get_current_user
from app.services.secure_work.intake.runs import trigger_of
from app.services.secure_work.intake.schedule import schedule_of
from app.time_utils import utc_now
from tests.tools.jira_impl.test_jira_task_list_governance import _operator

API = "/api/v1/secure-work/workspaces"


@pytest.fixture
async def api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://intake.test") as client:
        yield client, state


async def _workspace(db, *, jira: bool = True, confluence_source: bool = False) -> str:
    project = Project(name=f"ws-{uuid.uuid4().hex[:8]}", config={})
    db.add(project)
    await db.flush()
    if jira:
        db.add(BuiltInToolConfig(tool_name="jira", project_id=project.id, is_active=True,
                                 config={"jira_url": "https://jira.example.test", "jira_allowed_projects": ["CLM"]}))
        connector = KnowledgeSourceConnector(project_id=project.id, connector_key="claims-jira", kind="jira",
                                             scope={"project_keys": ["CLM"]})
        db.add(connector)
        await db.flush()
        db.add(KnowledgeSourceSyncRun(connector_id=connector.id, project_id=project.id, state="completed",
                                      finished_at=utc_now()))
    if confluence_source:
        db.add(KnowledgeSourceConnector(project_id=project.id, connector_key="wiki", kind="confluence", scope={}))
    await db.commit()
    return project.id


async def _intake(db, project_id: str, admin: User, **values) -> WorkItemSyncConfig:
    row = WorkItemSyncConfig(project_id=project_id, created_by=admin.id, **{
        "name": "Claims incidents", "source_type": "servicenow", "filters_json": {"tables": ["incident"]},
        "sync_options_json": {"schedule": {"preset": "every_15_min"}}, **values})
    db.add(row)
    await db.commit()
    return row


async def test_jira_in_knowledge_without_an_intake_reads_no_intake(db, api, auth_user):
    client, state = api
    project_id = await _workspace(db)
    state["user"] = auth_user
    body = (await client.get(f"{API}/{project_id}/intake")).json()
    sources = {source["kind"]: source for source in body["sources"]}
    assert set(sources) == {"jira", "servicenow"}
    jira = sources["jira"]
    assert jira["work_state"] == "no_intake" and jira["work"] is None
    assert jira["connections"] == [{"id": "default", "name": "default", "scope": "workspace"}]
    assert jira["knowledge"]["sources"] == 1 and jira["knowledge"]["last_synced_at"]
    assert sources["servicenow"]["work_state"] == "no_connection"
    assert body["intakes"] == []


async def test_set_up_sources_named_connections_and_content_sources(db, api, auth_user):
    client, state = api
    project_id = await _workspace(db, confluence_source=True)
    other = await _workspace(db)
    db.add(BuiltInToolConfig(tool_name="servicenow", project_id=project_id, is_active=True,
                             config={"servicenow_url": "https://sn.example.test"}))
    db.add(ConnectorNamedConnection(tool_name="jira", project_id=project_id, scope_key=project_id,
                                    name="team-cloud", config={}, bound_scopes=["OPS"]))
    row = await _intake(db, project_id, auth_user)
    await _intake(db, other, auth_user, name="Other Workspace intake")
    db.add(WorkItem(project_id=project_id, sync_config_id=row.id, source_type="servicenow", source_instance="sn",
                    source_key="INC1", title="Upload 502", work_state="intake"))
    row.last_sync_at, row.last_sync_status = utc_now(), "completed"
    await db.commit()
    state["user"] = auth_user
    body = (await client.get(f"{API}/{project_id}/intake")).json()
    sources = {source["kind"]: source for source in body["sources"]}
    assert [c["name"] for c in sources["jira"]["connections"]] == ["default", "team-cloud"]
    assert sources["servicenow"]["work_state"] == "set_up"
    assert sources["servicenow"]["work"]["items"] == 1 and sources["servicenow"]["work"]["active"] == 1
    assert sources["confluence"]["work_state"] == "not_a_work_source"
    assert [intake["name"] for intake in body["intakes"]] == ["Claims incidents"]
    intake = body["intakes"][0]
    assert intake["schedule"] == {"preset": "every_15_min", "cron": None}
    assert intake["what"]["tables"] == ["incident"] and intake["connection"]["name"] == "default"


async def test_run_history_is_newest_first_with_its_trigger(db, api, auth_user):
    client, state = api
    project_id = await _workspace(db)
    row = await _intake(db, project_id, auth_user)
    now = utc_now()
    for minutes, trigger in ((30, None), (15, "scheduled"), (0, "manual")):
        summary = {"imported": 1} | ({"trigger": trigger} if trigger else {})
        db.add(WorkItemSyncRun(sync_config_id=row.id, triggered_by=auth_user.id, mode="sync", status="completed",
                               summary_json=summary, created_at=now - timedelta(minutes=minutes)))
    await db.commit()
    state["user"] = auth_user
    runs = (await client.get(f"{API}/{project_id}/intake/{row.id}/runs")).json()["runs"]
    assert [run["trigger"] for run in runs] == ["manual", "scheduled", None]
    other = await _workspace(db)
    assert (await client.get(f"{API}/{other}/intake/{row.id}/runs")).status_code == 404


async def test_access_is_refused_outside_the_workspace(db, api):
    client, state = api
    project_id = await _workspace(db)
    operator = await _operator(db)
    state["user"] = operator
    assert (await client.get(f"{API}/{project_id}/intake")).status_code == 404
    db.add(UserProject(user_id=operator.id, project_id=project_id, role="member"))
    await db.commit()
    assert (await client.get(f"{API}/{project_id}/intake")).status_code == 200
    assert (await client.get(f"{API}/{uuid.uuid4()}/intake")).status_code == 404
    member = User(username=f"m-{uuid.uuid4().hex[:6]}", email=f"m-{uuid.uuid4().hex[:6]}@example.test",
                  password_hash="x", display_name="m", account_type="human", is_active=True)
    db.add(member)
    await db.flush()
    db.add(UserProject(user_id=member.id, project_id=project_id, role="member"))
    await db.commit()
    state["user"] = member
    assert (await client.get(f"{API}/{project_id}/intake")).status_code == 403


def test_schedules_read_as_one_preset_and_triggers_as_manual_or_scheduled():
    assert schedule_of({}) == {"preset": "manual", "cron": None}
    assert schedule_of({"schedule": {"preset": "custom", "cron": "*/30 * * * *"}}) == {
        "preset": "custom", "cron": "*/30 * * * *"}
    assert schedule_of({"schedule": {"preset": "hourly", "cron": "ignored"}}) == {"preset": "hourly", "cron": None}
    assert schedule_of({"schedule": {"preset": "daily_0600"}})["preset"] == "daily_0600"
    assert trigger_of({"trigger": "scheduler"}) == "scheduled" and trigger_of({}) == "manual"
