"""E1: no connector read stays unsourced without a stated reason.

Registry-wide contract over ``tests/connector_evidence_coverage_catalog.py``:

1. Every connector read tool in the live registry (an entry with a ``connector`` that does not mutate
   state) is in exactly one table: sourced, linked when its web URL is configured
   (``tests/test_connector_web_url_sources.py`` runs those), or unsourced with a closed, justified
   reason. A new connector read tool fails here until it is classified.
2. Every sourced tool is run against a stubbed connector API and emits items with ``source_title``,
   ``source_url`` and ``cite_as``, and every ``source_url`` lies on the connector's configured (or, for
   the fixed public SaaS APIs, the vendor's) web host. A URL is never built for an unknown host.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import pytest

from app.tools.registry import TOOL_REGISTRY_ENTRIES
from tests.connector_evidence_coverage_catalog import (
    SOURCED_CONNECTOR_READS,
    UNSOURCED_CONNECTOR_READS,
    UNSOURCED_REASONS,
    WEB_URL_LINKED_CONNECTOR_READS,
)
from tests.connector_evidence_coverage_scenarios import SCENARIOS
from tests.connector_evidence_coverage_support import (
    JIRA_ROUTES,
    SHAREPOINT,
    SYS_ID,
    _context,
    _http_json,
    _jira_get,
    _run,
)


def _connector_reads() -> set[str]:
    return {entry.name for entry in TOOL_REGISTRY_ENTRIES.values() if entry.connector and not entry.mutates_state}


def test_every_connector_read_tool_is_classified_exactly_once() -> None:
    reads = _connector_reads()
    unsourced = set(UNSOURCED_CONNECTOR_READS)
    linked = set(WEB_URL_LINKED_CONNECTOR_READS)
    tables = (SOURCED_CONNECTOR_READS, linked, unsourced)
    assert all(not a & b for i, a in enumerate(tables) for b in tables[i + 1 :]), "one table per tool"
    assert reads - SOURCED_CONNECTOR_READS - linked - unsourced == set(), "classify every connector read tool"
    assert (SOURCED_CONNECTOR_READS | linked | unsourced) - reads == set(), "no stale names in the tables"
    assert set(UNSOURCED_CONNECTOR_READS.values()) <= set(UNSOURCED_REASONS)
    assert all(len(text) > 40 for text in UNSOURCED_REASONS.values()), "every reason is justified"


# --- the contract ---------------------------------------------------------------------------------------


def _source_items(value: Any) -> list[dict]:
    if isinstance(value, dict):
        own = [value] if "source_url" in value else []
        return own + [item for child in value.values() for item in _source_items(child)]
    if isinstance(value, list):
        return [item for child in value for item in _source_items(child)]
    return []


def test_every_sourced_tool_has_a_scenario() -> None:
    assert set(SCENARIOS) == SOURCED_CONNECTOR_READS


@pytest.mark.asyncio
@pytest.mark.parametrize("name", sorted(SOURCED_CONNECTOR_READS))
async def test_a_sourced_connector_read_emits_source_fields_on_its_configured_host(name, db, monkeypatch) -> None:
    result, hosts = await SCENARIOS[name](db, monkeypatch, name)
    assert "error" not in result, result
    items = _source_items(result)
    assert items, f"{name} emitted no source fields: {result}"
    for item in items:
        assert urlsplit(item["source_url"]).hostname in hosts, item
        assert item["cite_as"].endswith(f"]({item['source_url']})") and item["source_title"]


@pytest.mark.asyncio
async def test_no_configured_base_means_no_source_fields(monkeypatch) -> None:
    _jira_get(monkeypatch, JIRA_ROUTES)
    result = await _run("search_jira_tickets", {"jql": "x"}, _context(jira_url="jira.example.test"))
    assert _source_items(result) == [], "a base without a scheme is not a known host"

    routes = {"/api/now/table/": {"result": [{"sys_id": SYS_ID, "number": "INC1"}]}}
    monkeypatch.setattr("app.tools.connectors.servicenow._http_json", _http_json(routes))
    record = await _run("list_servicenow_records", {"table": "incident"}, _context(servicenow_url="acme"))
    assert _source_items(record) == []


@pytest.mark.asyncio
async def test_an_api_web_url_on_a_foreign_host_is_never_a_source(monkeypatch) -> None:
    page = {"id": "p1", "object": "page", "url": "https://evil.example/p1", "properties": {}}
    monkeypatch.setattr("app.tools.connectors.notion._http_json", _http_json({"/search": {"results": [page]}}))
    assert _source_items(await _run("search_notion_pages", {"query": "x"}, _context())) == []

    sites = {"/v1.0/sites": {"value": [{"id": "s", "displayName": "Ops", "webUrl": "https://other.sharepoint.com/sites/ops"}]}}
    monkeypatch.setattr("app.tools.connectors.sharepoint._http_json", _http_json(sites))
    found = await _run("search_sharepoint", {"query": "ops"}, _context(sharepoint_url=SHAREPOINT, microsoft_graph_access_token="t"))
    assert _source_items(found) == []


@pytest.mark.asyncio
async def test_linear_issues_link_only_through_the_public_api(monkeypatch) -> None:
    async def fake_graphql(context, query, variables=None):
        node = {"id": "i1", "identifier": "OPS-1", "title": "Drill", "url": "https://linear.app/acme/issue/OPS-1"}
        return {"team": {"name": "Ops", "issues": {"nodes": [node]}}}

    monkeypatch.setattr("app.tools.connectors.issues._linear_graphql", fake_graphql)
    public = _context(linear_api_key="k", linear_allowed_team_ids=["t1"])
    issue = (await _run("list_issues", {"team_id": "t1"}, public))["issues"][0]
    assert issue["source_url"] == "https://linear.app/acme/issue/OPS-1"

    proxied = _context(linear_api_key="k", linear_allowed_team_ids=["t1"], linear_url="https://linear-proxy.example/graphql")
    assert _source_items(await _run("list_issues", {"team_id": "t1"}, proxied)) == []
