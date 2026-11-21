"""The work item sync pages by token and reads descriptions as text, state write-back posts ADF comments on v3, Server/DC keeps its shapes, and a story takes its epic as parent."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

import app.services.secure_work.jira.jira_connector as connector_module
import app.services.secure_work.jira.jira_state_sync as state_sync_module
from app.services.secure_work.jira.jira_mapping import jira_issue_to_work_item_payload
from app.services.secure_work.sync_policy import SYNC_MODE_EXECUTE
from app.tools.jira_impl._jira_cloud import text_to_adf
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from app.tools.jira_impl._jira_query_ticket_actions import AddJiraComment
from app.tools.jira_impl._jira_ticket_tools import CreateJiraTicket
from tests.jira_cloud_api_support import (  # noqa: F401
    MODULES,
    _cloud_config,
    _context,
    _no_server_only_request,
    cloud,
)

DC_URL = "https://jira.example.com/jira"


# --- secure_work on Jira Cloud --------------------------------------------------------------------------


def _sync_config() -> SimpleNamespace:
    return SimpleNamespace(project_id="p1", id="c1", connector_name="jira", connection_id=None, source_instance="cloud",
                           sync_options_json={"limit": 50}, field_mapping_json={})


@pytest.mark.asyncio
async def test_the_work_item_sync_pages_by_token_and_reads_descriptions_as_text(cloud, monkeypatch):  # noqa: F811
    import app.tools.jira_impl._jira_cloud as cloud_module

    async def config(_db, _config):
        return _cloud_config()

    monkeypatch.setattr(connector_module, "_resolve_jira_connector_config", config)
    monkeypatch.setattr(cloud_module, "CLOUD_PAGE_SIZE", 3)

    result = await connector_module.fetch_jira_issues_for_sync(None, config=_sync_config(), jql="project = OPS", limit=50)

    assert [issue["key"] for issue in result["issues"]] == [f"OPS-{n}" for n in range(1, 8)]
    assert (result["source_complete"], result["source_count"], result["metadata"]["api_version"]) == (True, 7, "3")
    tokens = [request["body"].get("nextPageToken") for request in cloud if request["path"] == "/rest/api/3/search/jql"]
    assert tokens == [None, "page-3", "page-6"], "native token paging, never startAt"
    _no_server_only_request(cloud)
    payload = jira_issue_to_work_item_payload(result["issues"][0], _sync_config())
    assert payload["description"] == "First paragraph of OPS-1.\n\nSecond paragraph."


@pytest.mark.asyncio
async def test_state_sync_write_back_posts_an_adf_comment_on_v3(cloud, monkeypatch):  # noqa: F811
    async def item_connection(_db, _item, connector):
        assert connector == "jira"
        return _cloud_config(), None

    # The write-back uses the connection serving the item (its intake's or its project's), not the project config.
    monkeypatch.setattr(state_sync_module, "work_item_connection_config", item_connection)
    item = SimpleNamespace(source_type="jira", source_key="OPS-2", project_id="p1", title="T", id="w1")
    workflow = SimpleNamespace(sync_policy_json={"sync_mode": SYNC_MODE_EXECUTE})
    preview = {"to_state": "review", "jira_sync_preview": {"sync_back": True, "comment_template": "Moved to review"}}

    result = await state_sync_module.execute_jira_state_sync(None, item=item, workflow=workflow, preview=preview)

    assert result["comment_posted"] is True
    [post] = cloud
    assert (post["path"], post["body"]) == ("/rest/api/3/issue/OPS-2/comment", {"body": text_to_adf("Moved to review")})


# --- Server/Data Center unchanged -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_dc_keeps_search_with_start_at_wiki_text_and_names(monkeypatch):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append({"method": request.method, "path": request.url.path, "params": dict(request.url.params), "body": body})
        if "/rest/api/3/" in request.url.path:
            return httpx.Response(404, json={})  # Server/DC has no v3
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"issues": [{"id": "1", "key": "OPS-1", "fields": {"summary": "s"}}], "total": 1})
        return httpx.Response(201, json={"id": "9"})

    transport = httpx.MockTransport(handler)
    for module in MODULES:
        monkeypatch.setattr(module, "egress_transport", lambda *_args, **_kwargs: transport)
    context = _context({"jira_url": DC_URL, "jira_username": "u", "jira_password": "p", "jira_auth_mode": "basic"})

    found = await SearchJiraTickets().execute({"jql": "project = OPS", "start_at": 5, "limit": 2}, context)
    await AddJiraComment().execute({"ticket_id": "OPS-1", "body": "wiki *text*"}, context)

    search = next(request for request in seen if request["path"] == "/jira/rest/api/2/search")
    assert (search["method"], search["params"]["startAt"], found["total"]) == ("GET", "5", 1)
    comment = next(request for request in seen if request["path"] == "/jira/rest/api/2/issue/OPS-1/comment")
    assert comment["body"] == {"body": "wiki *text*"}
    assert not any("search/jql" in request["path"] for request in seen)


# --- teamwork story split: a story under its epic on Jira Cloud -----------------------------------------


@pytest.mark.asyncio
async def test_a_story_is_created_under_its_epic_as_parent(cloud):  # noqa: F811
    created = await CreateJiraTicket().execute(
        {"project_key": "OPS", "summary": "Search dishes", "issue_type": "Story", "parent_key": "ops-1"},
        _context(_cloud_config()),
    )
    assert created["ticket_id"] == "OPS-100"
    [create] = [request for request in cloud if request["method"] == "POST" and request["path"] == "/rest/api/3/issue"]
    assert create["body"]["fields"]["parent"] == {"key": "OPS-1"}


@pytest.mark.parametrize(("parent", "expected"), [
    ({"key": "OPS-1", "fields": {"issuetype": {"name": "Epic", "hierarchyLevel": 1}}}, "OPS-1"),
    ({"key": "OPS-1", "fields": {"issuetype": {"name": "Initiative-Epos", "hierarchyLevel": 1}}}, "OPS-1"),
    ({"key": "OPS-7", "fields": {"issuetype": {"name": "Story", "hierarchyLevel": 0}}}, None),  # a sub-task's story
    (None, None),
])
def test_a_synced_cloud_story_takes_its_epic_from_the_parent(parent, expected):
    issue = {"key": "OPS-11", "fields": {"summary": "Search dishes", "issuetype": {"name": "Story"},
                                         **({"parent": parent} if parent else {})}}
    payload = jira_issue_to_work_item_payload(issue, _sync_config())
    assert payload["epic_key"] == expected
    assert payload["parent_key"] == (parent or {}).get("key")
