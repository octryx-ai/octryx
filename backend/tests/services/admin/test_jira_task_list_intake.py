"""Contract (B-1, B-2, B-3, B-4, B-7, B-8): the Jira intake of the task list, on Cloud and Server/DC."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import Project, User, WorkItem, WorkItemSyncConfig, WorkItemSyncRun
from app.services.admin.project.admin_project_connector_access_service import list_project_connector_access
from app.services.secure_work.jira.jira_sync_task import run_scheduled_jira_work_item_sync
from app.tools.context import ToolContext
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import (
    DcJira,
    cloud_config,
    cloud_transport,
    dc_config,
    dc_issue,
    use_transport,
    workspace_jira,
)


async def _intake(db, project_id: str, **filters) -> dict:
    return await create_jira_intake(db, {
        "name": f"intake-{uuid.uuid4().hex[:6]}", "project_id": project_id, "filters": filters})


async def _items(db, project_id: str) -> dict[str, WorkItem]:
    rows = (await db.execute(select(WorkItem).where(WorkItem.project_id == project_id))).scalars().all()
    return {row.source_key: row for row in rows}


async def test_b1_cloud_intake_reads_only_the_allowlist(client, auth_headers, db, monkeypatch):
    seen: list[dict] = []
    use_transport(monkeypatch, cloud_transport(seen))
    project_id = await workspace_jira(db, cloud_config(["BRD"]))

    with pytest.raises(HTTPException) as refused:
        await _intake(db, project_id, project_keys=["OPS"])
    assert refused.value.status_code == 409 and refused.value.detail["reason"] == "scope_not_allowed"
    assert refused.value.detail["projects"] == ["OPS"]
    await db.rollback()

    # A free JQL naming another project: restricted to the allowlist, and the stub (which ignores the
    # project clause) answers with OPS issues that are never persisted.
    created = await _intake(db, project_id, jql="project = OPS ORDER BY created DESC")
    for dry_run in (True, False):
        run = await run_jira_intake(db, created["id"], dry_run=dry_run)
        summary = run["sync_run"]["summary"]
        # That issues were filtered, never how many of another project exist.
        assert summary["filtered_outside_allowlist"] is True and summary["allowed_projects"] == ["BRD"]
        assert "outside_allowlist" not in summary
    searches = [request["body"]["jql"] for request in seen if request["path"].endswith("/search/jql")]
    assert searches and all(jql.startswith("project in (BRD) AND (project = OPS)") for jql in searches)
    assert all(jql.endswith("ORDER BY created DESC") for jql in searches)
    assert await _items(db, project_id) == {}


async def test_b1_dc_intake_drops_other_projects_and_allowed_ones_import(client, auth_headers, db, monkeypatch):
    jira = DcJira([dc_issue("OCX-1"), dc_issue("OPS-2")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    created = await _intake(db, project_id, project_keys=["OCX"])
    run = await run_jira_intake(db, created["id"])
    assert run["sync_run"]["summary"]["filtered_outside_allowlist"] is True
    jql = next(request["query"]["jql"][0] for request in jira.requests if request["path"] == "/rest/api/2/search")
    assert jql.startswith('project in (OCX) AND (project in ("OCX"))')
    assert set(await _items(db, project_id)) == {"OCX-1"}

    await run_jira_intake(db, created["id"], {"issues": [dc_issue("OPS-9"), dc_issue("OCX-9")]})
    assert set(await _items(db, project_id)) == {"OCX-1", "OCX-9"}


async def test_b1_b7_a_narrowed_allowlist_refuses_the_run_and_records_it(client, auth_headers, db, monkeypatch):
    use_transport(monkeypatch, DcJira([dc_issue("OCX-1")]).transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    created = await _intake(db, project_id, project_keys=["OCX"])
    config_id = created["id"]
    from app.models import BuiltInToolConfig

    entry = (await db.execute(select(BuiltInToolConfig).where(
        BuiltInToolConfig.project_id == project_id, BuiltInToolConfig.tool_name == "jira"))).scalar_one()
    entry.config = {**entry.config, "jira_allowed_projects": ["BRD"]}
    await db.commit()

    with pytest.raises(HTTPException) as refused:
        await run_jira_intake(db, config_id)
    assert refused.value.status_code == 409
    await db.rollback()
    owner = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    task = SimpleNamespace(config={"sync_config_id": config_id}, owner_id=owner.id)
    try:
        await run_scheduled_jira_work_item_sync(db, task=task, task_run=SimpleNamespace(output=None))
        raise AssertionError("the scheduled run must be refused too")
    except Exception as exc:  # noqa: BLE001 - the refusal itself
        assert getattr(exc, "status_code", None) == 409
    config = await db.get(WorkItemSyncConfig, config_id)
    await db.refresh(config)
    assert config.last_sync_status == "failed" and config.last_sync_summary_json["code"] == "scope_not_allowed"
    runs = (await db.execute(select(WorkItemSyncRun).where(WorkItemSyncRun.sync_config_id == config_id))).scalars()
    assert [run.status for run in runs].count("failed") == 2
    assert await _items(db, project_id) == {}


async def test_b2_b3_b4_states_people_and_comments_on_dc_and_cloud(client, auth_headers, db, monkeypatch):
    jira = DcJira([
        dc_issue("OCX-1", status={"name": "Zu erledigen", "statusCategory": {"key": "new"}}),
        dc_issue("OCX-2", status={"name": "In Arbeit", "statusCategory": {"key": "indeterminate"}}),
        dc_issue("OCX-3", status={"name": "In Progress", "statusCategory": {"key": "indeterminate"}}),
    ])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    created = await _intake(db, project_id, project_keys=["OCX"])
    run = await run_jira_intake(db, created["id"])
    assert run["sync_run"]["summary"]["status_category_statuses"] == {"Zu erledigen": 1, "In Arbeit": 1}
    listing = (await client.get(f"/api/v1/secure-work/work-items?sync_config_id={created['id']}",
                                headers=auth_headers)).json()["items"]
    items = {item["source_key"]: item for item in listing}
    assert (items["OCX-1"]["work_state"], items["OCX-1"]["status_mapping"]) == (
        "intake", {"source": "status_category", "category": "new"})
    assert items["OCX-2"]["work_state"] == "development" and items["OCX-3"]["work_state"] == "development"
    assert items["OCX-3"]["status_mapping"]["source"] == "builtin"
    assert "comments" not in items["OCX-1"] and items["OCX-1"]["comments_total"] == 1
    item = (await client.get(f"/api/v1/secure-work/work-items/{items['OCX-1']['id']}", headers=auth_headers)).json()
    assert (item["assignee"], item["assignee_display"], item["reporter_display"]) == ("jdoe", "Jane Doe", "Richard Roe")
    comment = item["comments"][0]
    assert (comment["author"], comment["author_display"], comment["body"]) == ("rroe", "Richard Roe", "Please check *this*.")
    assert comment["created"] == "2026-10-03T06:00:00+00:00" and comment["url"].endswith("/browse/OCX-1?focusedCommentId=900")
    assert item["sprint"] is None and item["board"] is None and item["comments_total"] == 1
    filtered = await client.get(f"/api/v1/secure-work/work-items?assignee=jdoe&project_id={project_id}",
                                headers=auth_headers)
    assert filtered.status_code == 200 and {i["source_key"] for i in filtered.json()["items"]} >= {"OCX-1"}


async def test_b3_b4_cloud_people_and_adf_comments(client, auth_headers, db, monkeypatch):
    seen: list[dict] = []
    use_transport(monkeypatch, cloud_transport(seen))
    project_id = await workspace_jira(db, cloud_config(["OPS"]))
    # The stub's issues carry no ``project`` field (real Cloud does), so the intake filters by JQL.
    created = await _intake(db, project_id, jql="project = OPS")
    synced = await run_jira_intake(db, created["id"])
    assert synced["sync_run"]["summary"]["imported"] == 7, synced
    fields = next(request["body"]["fields"] for request in seen if request["path"].endswith("/search/jql"))
    assert "comment" in fields
    row = (await client.get(f"/api/v1/secure-work/work-items?sync_config_id={created['id']}",
                            headers=auth_headers)).json()["items"][0]
    item = (await client.get(f"/api/v1/secure-work/work-items/{row['id']}", headers=auth_headers)).json()
    assert item["assignee"] == "5b10ac8d82e05b22cc7d4ef5" and item["assignee_display"] == "Ada Lovelace"
    assert item["comments"][0]["author_display"] == "Alan Turing"
    assert item["comments"][0]["body"] == "Looks good to me." and item["comments"][0]["created"].endswith("+00:00")


async def test_b7_an_invalid_jql_is_coded_in_the_intake_and_the_tool(client, auth_headers, db, monkeypatch):
    jira = DcJira([dc_issue("OCX-1")], refuse_jql_with="BROKEN")
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(None))
    created = await _intake(db, project_id, jql="BROKEN = 1")
    with pytest.raises(HTTPException) as refused:
        await run_jira_intake(db, created["id"])
    assert refused.value.status_code == 422 and refused.value.detail["code"] == "jql_invalid"
    assert "Field 'BROKEN' does not exist." in refused.value.detail["message"]
    await db.rollback()
    config = await db.get(WorkItemSyncConfig, created["id"])
    await db.refresh(config)
    assert config.last_sync_summary_json["code"] == "jql_invalid"
    assert "BROKEN" in config.last_sync_summary_json["message"] and "pw" not in str(config.last_sync_summary_json)

    context = ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1",
                          project_config=dc_config(None), capability_type="change", agent_mode_key="change",
                          workspace_root="/tmp")
    result = await SearchJiraTickets().execute({"jql": "BROKEN = 1"}, context)
    assert result["code"] == "jql_invalid" and "Field 'BROKEN' does not exist." in result["message"]


async def test_b8_the_workspace_connector_list_always_has_jira_and_confluence(db):
    project = Project(name=f"fresh-{uuid.uuid4().hex[:8]}")
    db.add(project)
    await db.commit()
    listing = await list_project_connector_access(db, project_id=project.id)
    names = {connector["connector_name"]: connector for connector in listing["connectors"]}
    assert {"jira", "confluence"} <= set(names)
    assert names["confluence"]["project_configured"] is False
