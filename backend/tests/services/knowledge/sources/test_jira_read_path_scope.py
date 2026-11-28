"""Contract: defence in depth on every Jira read path (breakout strings refused or filtered), and Workspace scope on
every secure-work route."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import WorkItem
from app.services.knowledge.ledger.errors import InvalidEvidenceRequestError
from app.services.knowledge.sources.sync.config import validate_config
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.http import SourceReader
from app.services.knowledge.sources.sync.jira import JiraConnector, build_jql
from app.services.knowledge.sources.sync.jira_releases import release_jql, search_release_issues
from app.services.secure_work.jira.jira_scope import restrict_jql
from app.tools.jira_impl._jira_allowlist import allowed_issues
from app.tools.jira_impl._jira_helpers_jql import _inject_project_restriction
from app.tools.jira_impl._jira_jql_confine import UnsafeJqlError, jql_problem
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from app.tools.registry import ToolContext
from tests.egress_support import public_source_dns  # noqa: F401 - the fixture, used by name
from tests.jira_intake_support import create_jira_intake, run_jira_intake
from tests.jira_task_list_support import (
    DcJira,
    dc_config,
    dc_issue,
    scoped_api,  # noqa: F401 - fixture
    use_transport,
    workspace_jira,
)
from tests.services.knowledge.sources.test_jira_cloud_source_sync import _connection
from tests.services.knowledge.sources.test_jira_cloud_source_sync import _transport as cloud_transport
from tests.tools.jira_impl.test_jira_task_list_governance import _item, _operator, _workflow

API = "/api/v1/secure-work"
BACKSLASH_BREAKOUT = r'summary ~ \"a) OR project = OPS OR (summary ~ "b \" c"'
KEY_BREAKOUT = 'BRD-1")OR(key="OPS-1")OR(key="BRD-1'


def _context(allowed: list[str]) -> ToolContext:
    return ToolContext(user_id="u1", project_ids=[], roles=["admin"], session_id="s1",
                       project_config=dc_config(allowed), capability_type="change", agent_mode_key="change",
                       workspace_root="/tmp")


def test_c1b_a_backslash_outside_quotes_is_refused_everywhere():
    assert jql_problem(BACKSLASH_BREAKOUT) == "jql_invalid"
    assert jql_problem(r'summary ~ "a \" b"') is None, "an escape inside quotes is fine"
    for confine in (lambda: restrict_jql(BACKSLASH_BREAKOUT, frozenset({"BRD"})),
                    lambda: _inject_project_restriction(BACKSLASH_BREAKOUT, ["BRD"])):
        with pytest.raises(UnsafeJqlError):
            confine()
    with pytest.raises(InvalidEvidenceRequestError):
        validate_config(connector_key="ops", kind="jira", project_keys=["BRD"], jql=BACKSLASH_BREAKOUT)
    for stored in (lambda: build_jql(("BRD",), BACKSLASH_BREAKOUT), lambda: release_jql("BRD", "1", BACKSLASH_BREAKOUT)):
        with pytest.raises(ConnectorError):
            stored()


async def test_c1b_the_intake_and_the_tool_never_send_it(client, auth_headers, db, monkeypatch):
    jira = DcJira([dc_issue("BRD-1")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["BRD"]))
    created = await create_jira_intake(db, {
        "name": "esc", "project_id": project_id, "filters": {"jql": BACKSLASH_BREAKOUT}})
    run = await run_jira_intake(db, created["id"], dry_run=True)
    assert run["sync_run"]["status"] == "blocked" and run["sync_run"]["summary"]["block_reason"] == "jql_invalid"
    result = await SearchJiraTickets().execute({"jql": BACKSLASH_BREAKOUT}, _context(["BRD"]))
    assert result["code"] == "jql_invalid"
    assert not [request for request in jira.requests if request["path"].endswith("/search")]


async def test_c1b_free_text_and_keys_stay_literal_and_results_are_filtered(monkeypatch):
    jira = DcJira([dc_issue("BRD-1"), dc_issue("OPS-1"), dc_issue("BRD-2", project="OPS")])
    use_transport(monkeypatch, jira.transport())
    result = await SearchJiraTickets().execute({"query": KEY_BREAKOUT}, _context(["BRD"]))
    sent = jira.requests[-1]["query"]["jql"][0]
    assert 'OR(key="OPS-1")' not in sent and sent.startswith('project in ("BRD") AND (')
    assert 'text ~ "\\"BRD-1\\")OR(key=\\"OPS-1\\")' in sent, "the whole query is one escaped phrase"
    assert [issue["ticket_id"] for issue in result["results"]] == ["BRD-1"]
    assert result["total"] is None, "no count that includes filtered issues"
    keyed = await SearchJiraTickets().execute({"query": "brd-7"}, _context(["BRD"]))
    assert 'key = "BRD-7"' in keyed["jql"]
    assert allowed_issues([{"key": "BRD_1"}, {"key": "BRD-3", "fields": {}}], ["BRD"]) == [{"key": "BRD-3", "fields": {}}]


@pytest.mark.usefixtures("public_source_dns")  # the egress policy resolves the host: never real DNS
async def test_c1b_knowledge_lists_and_counts_only_its_own_projects():
    seen: list[dict] = []
    # The Cloud stub ignores the project clause and answers OPS issues.
    foreign = JiraConnector(_connection(), project_keys=("BRD",), transport=cloud_transport(seen))
    assert (await foreign.list_items(None, limit=10)).items == ()
    own = JiraConnector(_connection(), project_keys=("OPS",), transport=cloud_transport(seen))
    assert len((await own.list_items(None, limit=10)).items) == 7
    reader = SourceReader(_connection(), transport=cloud_transport(seen))
    issues, _ = await search_release_issues(reader, release_jql("BRD", "20002", None), fields="summary",
                                            bound=10, project_key="BRD")
    assert issues == []


async def test_c8_an_operator_outside_the_workspace_reads_and_drives_nothing(scoped_api, client, auth_headers, db, monkeypatch):  # noqa: F811
    api, state = scoped_api
    jira = DcJira([dc_issue("OCX-1")])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    item_id = await _item(db, project_id, "OCX-5")
    intake = (await create_jira_intake(db, {
        "name": "own", "project_id": project_id, "filters": {"project_keys": ["OCX"]}}))["id"]
    state["user"] = await _operator(db)
    listed = await api.get(f"{API}/work-items")
    assert listed.status_code == 200 and item_id not in {row["id"] for row in listed.json()["items"]}
    for path in ("state-events", "lifecycle", "coding-observability", "coding-pipeline"):
        assert (await api.get(f"{API}/work-items/{item_id}/{path}")).status_code == 404, path
    assert (await api.get(f"{API}/work-items?project_id={project_id}")).status_code == 403
    intakes = f"{API}/workspaces/{project_id}/intake"
    assert (await api.get(intakes)).status_code == 404
    assert (await api.get(f"{intakes}/{intake}")).status_code == 404
    assert (await api.put(f"{intakes}/{intake}", json={"name": "x"})).status_code == 404
    for route in ("preview", "sync"):
        assert (await api.post(f"{intakes}/{intake}/{route}", json={})).status_code == 404
    assert (await api.post(intakes, json={"source_type": "jira", "name": "mine"})).status_code == 404
    assert (await api.post(f"{API}/work-items/{item_id}/coding-pipeline/start", json={})).status_code == 404
    assert jira.requests == []


async def test_c9_links_preview_order_and_the_workflow_version(client, auth_headers, db, monkeypatch):
    jira = DcJira([{**dc_issue("OCX-1"), "fields": {**dc_issue("OCX-1")["fields"], "issuelinks": [
        {"type": {"name": "blocks"}, "outwardIssue": {"key": "OCX-2", "fields": {"summary": "own"}}},
        {"type": {"name": "relates"}, "outwardIssue": {"key": "OPS-9", "fields": {"summary": "secret"}}},
    ]}}])
    use_transport(monkeypatch, jira.transport())
    project_id = await workspace_jira(db, dc_config(["OCX"]))
    intake = (await create_jira_intake(db, {
        "name": "links", "project_id": project_id, "filters": {"project_keys": ["OCX"]}}))["id"]
    await run_jira_intake(db, intake)
    item = (await db.execute(select(WorkItem).where(WorkItem.source_key == "OCX-1"))).scalar_one()
    assert item.linked_issues_json[0]["outwardIssue"]["key"] == "OCX-2"
    assert item.linked_issues_json[1] == {"type": {"name": "relates"}, "external": True}
    assert "secret" not in str(item.source_fields_json) and "OPS-9" not in str(item.source_fields_json)

    workflow = await _workflow(client, auth_headers, project_id,
                               mappings={"development": {"comment_template": "moved", "sync_back": True}})
    outside = await _item(db, project_id, "OPS-3")
    dry = await client.post(f"{API}/workflows/{workflow['id']}/dry-run-transition", headers=auth_headers,
                            json={"work_item_id": outside, "to_state": "development"})
    preview = dry.json()["preview"]["jira_sync_preview"]
    assert (preview["will_mutate_jira"], preview["blocked_reason"], preview["effects"]) == (False, "scope_not_allowed", [])

    route = f"{API}/workflows/{workflow['id']}"
    loaded = workflow["updated_at"]
    assert (await client.put(route, headers=auth_headers, json={"description": "a", "updated_at": loaded})).status_code == 200
    stale = await client.put(route, headers=auth_headers, json={"description": "b", "updated_at": loaded})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "workflow_stale"
    off = await client.post(f"{route}/deactivate", headers=auth_headers, json={"updated_at": loaded})
    assert off.status_code == 409
    current = (await client.get(f"{API}/workflows?project_id={project_id}&include_inactive=true",
                                headers=auth_headers)).json()["items"]
    fresh = next(row for row in current if row["id"] == workflow["id"])["updated_at"]
    assert (await client.post(f"{route}/deactivate", headers=auth_headers, json={"updated_at": fresh})).status_code == 200

