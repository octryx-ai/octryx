"""Jira write-back, intake and reporter questions use the work item's connection, a ServiceNow work note uses its table's connection, and worker health, the flow builder and the pull request delivery record read the serving named connection."""

from __future__ import annotations

import httpx
import pytest

from app.models import BuiltInToolConfig, WorkItem, WorkItemSyncConfig
from app.services.admin.project.named_connection_service import save_named
from app.services.project.service import get_project_config
from tests.agent_definition_revision_fixtures import make_user
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.support.named_connection_service_lookups_support import ACCOUNT, OCTRYX, SECOND, _basic, _jira_workspace

pytestmark = pytest.mark.asyncio


async def _jira_item(db, workspace_id: str, key: str, *, intake_connection: str | None = None) -> WorkItem:
    sync_id = None
    if intake_connection is not None:
        owner = await make_user(db, label="intake")
        row = WorkItemSyncConfig(project_id=workspace_id, source_type="jira", source_instance="jira",
                                 connection_id=intake_connection, name="intake", created_by=owner.id)
        db.add(row)
        await db.flush()
        sync_id = row.id
    item = WorkItem(project_id=workspace_id, source_type="jira", source_instance="jira", source_key=key,
                    source_project_key=key.split("-")[0], title="t", sync_config_id=sync_id,
                    source_fields_json={"people": {"reporter": {"id": ACCOUNT, "display": "Dev"}}})
    db.add(item)
    await db.flush()
    return item


async def test_jira_write_back_uses_the_items_connection(db):
    from app.services.secure_work.jira import jira_state_sync

    workspace_id = await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]), ("Jira-B", SECOND, ["OPS"]))
    base_url, authorization, cloud, allowed, _auth = await jira_state_sync._jira_access(
        await _jira_item(db, workspace_id, "OPS-4"), db)
    assert (base_url, cloud, allowed) == (SECOND, True, frozenset({"OPS"}))
    assert authorization["Authorization"] == _basic("bot@jira-b.test", "token-jira-b")
    unserved = await jira_state_sync._jira_access(await _jira_item(db, workspace_id, "RIVER-1"), db)
    assert unserved[0] == ""  # no connection serves RIVER: nothing is written (the caller's "not configured")


async def test_an_items_intake_connection_is_named_and_never_replaced(db):
    from app.services.secure_work.item_connection import work_item_connection_config

    workspace_id = await _jira_workspace(db, ("Jira-A", OCTRYX, ["BRD"]), ("Jira-B", SECOND, ["OPS"]))
    config = await get_project_config(workspace_id, db)
    jira_a = next(c for c in config["named_connections"].of("jira") if c.name == "Jira-A")
    good, refused = await work_item_connection_config(
        db, await _jira_item(db, workspace_id, "BRD-2", intake_connection=jira_a.id), "jira")
    assert (good["jira_url"], refused) == (OCTRYX, None)
    _empty, moved = await work_item_connection_config(
        db, await _jira_item(db, workspace_id, "OPS-2", intake_connection=jira_a.id), "jira")
    assert moved == "connection_scope_mismatch"


async def test_reporter_questions_comment_through_the_items_connection(db, monkeypatch):
    from app.services.work_item_analysis import reporter_questions

    workspace_id = await _jira_workspace(db, ("Jira-Cloud-octryx", OCTRYX, ["BRD"]))
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "10001"})

    monkeypatch.setattr(reporter_questions, "egress_transport", lambda *_a, **_k: httpx.MockTransport(handle))
    posted = await reporter_questions._post(db, await _jira_item(db, workspace_id, "BRD-7"), ["Which browser?"])
    assert posted["state"] == reporter_questions.STATE_POSTED
    [request] = seen
    assert str(request.url) == f"{OCTRYX}/rest/api/3/issue/BRD-7/comment"
    assert request.headers["Authorization"] == _basic("bot@jira-cloud-octryx.test", "token-jira-cloud-octryx")
    skipped = await reporter_questions._post(db, await _jira_item(db, workspace_id, "RIVER-7"), ["Which browser?"])
    assert skipped["reason"] == "connection_not_configured_for_scope" and len(seen) == 1


async def test_a_servicenow_work_note_uses_the_connection_of_the_records_table(db):
    from fastapi import HTTPException

    from app.models import User
    from app.services.secure_work.item_connection import work_item_connection_config
    from app.services.secure_work.servicenow import worknote

    workspace_id = await seed_workspace(db)
    db.add(BuiltInToolConfig(tool_name="servicenow", project_id=workspace_id, is_active=True, config={}))
    await db.flush()
    await save_named(db, connector="servicenow", project_id=workspace_id, actor_id=None, payload={
        "name": "SN-Incidents", "bound_scopes": ["incident"], "servicenow_url": "https://sn.example.test",
        "servicenow_auth_mode": "basic", "servicenow_username": "bot", "servicenow_password": "pw"})
    incident = WorkItem(project_id=workspace_id, source_type="servicenow", source_instance="sn", source_key="INC1",
                        title="t", issue_type="incident", source_fields_json={"servicenow": {"table": "incident"}})
    change = WorkItem(project_id=workspace_id, source_type="servicenow", source_instance="sn", source_key="CHG1",
                      title="t", issue_type="change_request",
                      source_fields_json={"servicenow": {"table": "change_request"}})
    db.add_all([incident, change])
    await db.flush()
    config, refused = await work_item_connection_config(db, incident, "servicenow")
    assert (config["servicenow_url"], config["servicenow_password"], refused) == ("https://sn.example.test", "pw", None)
    with pytest.raises(HTTPException) as unserved:
        await worknote.send_worknote(db, item=change, user=User(id="u"), note_at=None, confirm=False)
    assert unserved.value.status_code == 409
    assert unserved.value.detail["code"] == "connection_not_configured_for_scope"




