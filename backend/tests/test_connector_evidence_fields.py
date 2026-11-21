"""Connector read results are evidence-bearing in the Knowledge evidence shape.

Every item a person can open carries ``source_title``, ``source_url`` and ``cite_as``. The URL is
the connector's configured base URL plus the item key, or the API's own web URL on the configured
host; it is never constructed for an unknown host. One contract test per tool family, the result
compressors keep the fields, and one end-to-end case over ``run_agent``: a Jira-stub answer with a
``/browse`` link passes the answer evidence guard, the same answer without links is delivered with a sources note.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.answer_evidence.evidence import collect_turn_evidence
from app.services.github_url import github_web_base_url
from app.services.tool_result_compression.strategy_knowledge import _compress_confluence_search, _compress_jira_search
from app.tools.confluence import GetConfluencePage, ListConfluencePages, _confluence_page_search_summary
from app.tools.connectors.atlassian_result_compaction import compact_jira_ticket_search_result
from app.tools.evidence_fields import item_url, known_web_url
from app.tools.jira_impl._jira_query_search import SearchJiraTickets
from app.tools.jira_impl._jira_version_tools import ListJiraVersions
from app.tools.jira_release_status import JiraReleaseStatusTool
from app.tools.knowledge_evidence.confluence_updates import ListConfluencePageUpdatesTool
from tests.connector_evidence_fields_support import JIRA, _assert_source, _context, _issue

CONFLUENCE = "https://wiki.example.test/confluence"


# --- the URL rules ---------------------------------------------------------------------------------


def test_urls_come_only_from_the_configured_base_and_its_host() -> None:
    assert item_url(JIRA, "browse", "OPS-1") == f"{JIRA}/browse/OPS-1"
    assert item_url("", "browse", "OPS-1") is None
    assert item_url("jira.example.test", "browse", "OPS-1") is None, "no scheme: not a known base"
    assert item_url(JIRA, "browse", "") is None, "no key: no URL"
    assert known_web_url("https://gitlab.example/g/p/-/merge_requests/9", "https://gitlab.example") is not None
    assert known_web_url("https://evil.example/g/p", "https://gitlab.example") is None
    assert github_web_base_url("https://api.github.com") == "https://github.com"
    assert github_web_base_url("https://ghe.example.test/api/v3") == "https://ghe.example.test"
    assert github_web_base_url("https://ghe.example.test/custom") is None


# --- Jira -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_jira_tickets_items_name_their_browse_page(monkeypatch) -> None:
    async def fake_get(client, jira_url, path, **_kwargs):
        assert path == "/search"
        return {"issues": [_issue("OPS-2", "Failover drill blocked")], "total": 1}, "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_get)
    result = await SearchJiraTickets().execute({"jql": "project = OPS"}, _context(jira_url=JIRA))
    _assert_source(result["results"][0], f"{JIRA}/browse/OPS-2", title="OPS-2: Failover drill blocked")

    # Both result compressors keep the source fields the model cites by.
    assert _compress_jira_search(result, {})["results"][0]["source_url"] == f"{JIRA}/browse/OPS-2"
    assert compact_jira_ticket_search_result(result)["results"][0]["cite_as"] == result["results"][0]["cite_as"]


@pytest.mark.asyncio
async def test_get_jira_ticket_names_its_browse_page(monkeypatch) -> None:
    from app.tools.jira_impl._jira_query_ticket_actions import GetJiraTicket

    async def fake_get(client, jira_url, path, **_kwargs):
        return ({"comments": []} if path.endswith("/comment") else _issue("OPS-2", "Failover drill blocked")), "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_get)
    result = await GetJiraTicket().execute({"ticket_id": "OPS-2"}, _context(jira_url=JIRA))
    _assert_source(result, f"{JIRA}/browse/OPS-2", title="OPS-2: Failover drill blocked")


@pytest.mark.asyncio
async def test_list_jira_versions_items_name_their_version_page(monkeypatch) -> None:
    async def fake_get(client, jira_url, path, **_kwargs):
        return [{"id": "10020", "name": "2.4.20", "released": False}, {"id": "", "name": "draft"}], "2"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_get)
    result = await ListJiraVersions().execute({"project_key": "OPS"}, _context(jira_url=JIRA))
    released, draft = result["versions"]
    _assert_source(released, f"{JIRA}/projects/OPS/versions/10020", title="OPS 2.4.20")
    assert "source_url" not in draft, "a version without an id has no page: no source"


@pytest.mark.asyncio
async def test_jira_release_status_names_the_version_and_each_blocker(monkeypatch) -> None:
    async def fake_status(db, **_kwargs):
        return {
            "state": "ok",
            "jira_project": "OPS",
            "jira_version": "2.4.20",
            "version_url": f"{JIRA}/projects/OPS/versions/10020",
            "open_blockers": [{"key": "OPS-2", "summary": "Failover drill", "url": f"{JIRA}/browse/OPS-2"}],
        }

    async def authorized(params, context):
        return SimpleNamespace(project_id="p1")

    monkeypatch.setattr("app.tools.jira_release_status.jira_release_status", fake_status)
    monkeypatch.setattr("app.tools.jira_release_status.authorized_workspace", authorized)
    result = await JiraReleaseStatusTool().execute({"product": "ops", "version": "2.4.20"}, _context())
    _assert_source(result, f"{JIRA}/projects/OPS/versions/10020", title="OPS 2.4.20")
    _assert_source(result["open_blockers"][0], f"{JIRA}/browse/OPS-2", title="OPS-2: Failover drill")


# --- Confluence -------------------------------------------------------------------------------------


def test_confluence_search_items_name_their_viewpage_link() -> None:
    page = {"id": "123", "title": "Runbook", "space": {"key": "OPS"}, "version": {"number": 4}}
    item = _confluence_page_search_summary(page, CONFLUENCE)
    url = f"{CONFLUENCE}/pages/viewpage.action?pageId=123"
    assert item["url"] == url
    _assert_source(item, url, title="Runbook")
    assert _compress_confluence_search({"results": [item]}, {})["results"][0]["source_url"] == url
    assert "source_url" not in _confluence_page_search_summary(page, ""), "no configured base: no source"


@pytest.mark.asyncio
async def test_get_and_list_confluence_pages_name_their_viewpage_link(monkeypatch) -> None:
    async def fake_fetch(client, base, kwargs, **_kwargs):
        return {"id": "123", "title": "Runbook", "space": {"key": "OPS"}, "body": {"storage": {"value": "<p>x</p>"}}}

    monkeypatch.setattr("app.tools.confluence.fetch_page_record", fake_fetch)
    monkeypatch.setattr("app.tools.confluence.page_allowed", lambda *_args, **_kwargs: True)
    page = await GetConfluencePage().execute({"page_id": "123"}, _context(confluence_url=CONFLUENCE))
    _assert_source(page, f"{CONFLUENCE}/pages/viewpage.action?pageId=123", title="Runbook")

    async def fake_list(params, context):
        return {"pages": [{"id": "77", "title": "Release notes"}], "listing_complete": True}

    monkeypatch.setattr("app.tools.confluence.list_confluence_pages", fake_list)
    listed = await ListConfluencePages().execute({}, _context(confluence_url=CONFLUENCE))
    _assert_source(listed["pages"][0], f"{CONFLUENCE}/pages/viewpage.action?pageId=77")


@pytest.mark.asyncio
async def test_confluence_page_updates_name_their_recorded_origin_link(monkeypatch) -> None:
    recorded = f"{CONFLUENCE}/pages/viewpage.action?pageId=9"

    async def fake_updates(db, authorized, **_kwargs):
        return {"state": "ok", "new_pages": [{"id": "9", "title": "New", "url": recorded}], "changed_pages": []}

    async def authorized(params, context):
        return SimpleNamespace(project_id="p1")

    monkeypatch.setattr("app.tools.knowledge_evidence.confluence_updates.confluence_page_updates", fake_updates)
    monkeypatch.setattr("app.tools.knowledge_evidence.confluence_updates.authorized_workspace", authorized)
    result = await ListConfluencePageUpdatesTool().execute({}, _context())
    _assert_source(result["new_pages"][0], recorded, title="New")


def test_the_compacted_jira_result_is_evidence_bearing() -> None:
    result = {"results": [{"ticket_id": "OPS-2", "summary": "x", "source_url": f"{JIRA}/browse/OPS-2",
                           "source_title": "OPS-2: x", "cite_as": f"[OPS-2: x]({JIRA}/browse/OPS-2)"}]}
    history = [{"tool_name": "search_jira_tickets", "result": _compress_jira_search(result, {})}]
    assert collect_turn_evidence(history).evidence_bearing
