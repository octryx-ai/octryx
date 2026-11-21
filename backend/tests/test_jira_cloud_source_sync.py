"""Jira Cloud for Source Sync and releases (root decision (a)): the governed reader, listing, rendering, releases.

Behind the Cloud-shaped stub (``jira_stub_cloud.py``), which refuses every Server/DC-only shape:

- the issue listing pages by Jira's ``nextPageToken`` over ``POST /rest/api/3/search/jql`` (token ``c:<token>``);
  a token of the other API never pages on;
- ADF descriptions and comments render as text (``jira_render._body``), in issues and release notes;
- release issues are searched the same way; completeness comes from the last page, not a Cloud ``total``;
- ``SourceReader`` sends POST only for exactly the fixed search path: any other POST is refused before it is sent;
- an empty page while the source says more remain ends the release issues as truncated, never as complete;
- a malformed ADF node degrades to the text it still carries; rendering an issue never raises.

No network: the egress policy sees a public test address (``public_source_dns``) and a mock transport answers.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.models.project.knowledge_source_sync import CONNECTOR_KIND_JIRA
from app.services.knowledge.sources.sync.connections import SourceConnection
from app.services.knowledge.sources.sync.contract import ConnectorError
from app.services.knowledge.sources.sync.http import SourceReader
from app.services.knowledge.sources.sync.jira import JiraConnector
from app.services.knowledge.sources.sync.jira_release_config import ReleaseConfig
from app.services.knowledge.sources.sync.jira_releases import release_jql, search_release_issues
from app.services.knowledge.sources.sync.jira_render import _body, render_issue
from app.tools.jira_impl._jira_cloud import text_to_adf
from tests import source_stub_support as stubs
from tests.egress_support import public_source_dns  # noqa: F401  (fixture)

pytestmark = pytest.mark.usefixtures("public_source_dns")

cloud_stub = stubs.load("jira_stub_cloud")
CLOUD = "https://your-site.atlassian.net"
RELEASES = ReleaseConfig(products=(("OPS", "acme-orders"),))


def _connection(base_url: str = CLOUD) -> SourceConnection:
    return SourceConnection(
        kind=CONNECTOR_KIND_JIRA, base_url=base_url, principal=cloud_stub.CLOUD_EMAIL, secret=cloud_stub.CLOUD_TOKEN,
        allowed_scopes=frozenset({"OPS"}),
    )


def _transport(seen: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append({"method": request.method, "path": request.url.path, "body": body})
        status, payload = cloud_stub.handle(
            request.method, request.url.raw_path.decode(), request.headers.get("Authorization"), body
        )
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _only_cloud_requests(seen: list[dict]) -> None:
    for request in seen:
        assert request["path"] not in {"/rest/api/2/search", "/rest/api/3/search"}
        assert request["method"] == "GET" or request["path"] == "/rest/api/3/search/jql", request


@pytest.mark.asyncio
async def test_the_issue_listing_pages_by_cloud_token_and_renders_adf_as_text():
    seen: list[dict] = []
    connector = JiraConnector(_connection(), project_keys=("OPS",), transport=_transport(seen))

    first = await connector.list_items(None, limit=3)
    second = await connector.list_items(first.next_token, limit=3)
    last = await connector.list_items(second.next_token, limit=3)

    assert (first.next_token, second.next_token, last.next_token) == ("c:page-3", "c:page-6", None)
    assert [item.external_id for page in (first, second, last) for item in page.items] == [
        str(10000 + n) for n in range(1, 8)
    ]
    searches = [request for request in seen if request["path"] == "/rest/api/3/search/jql"]
    assert [request["body"].get("nextPageToken") for request in searches] == [None, "page-3", "page-6"]
    assert all("comment" in request["body"]["fields"] and "description" in request["body"]["fields"] for request in searches)
    _only_cloud_requests(seen)

    rendered = (await connector.fetch(first.items[0])).data.decode()
    assert "First paragraph of OPS-1.\n\nSecond paragraph." in rendered
    assert "Looks good to me." in rendered and "'type': 'doc'" not in rendered


@pytest.mark.asyncio
async def test_the_release_phase_follows_and_renders_cloud_issue_descriptions():
    seen: list[dict] = []
    connector = JiraConnector(_connection(), project_keys=("OPS",), releases=RELEASES, transport=_transport(seen))

    issues = await connector.list_items(None, limit=100)
    releases = await connector.list_items(issues.next_token, limit=100)

    assert issues.next_token == "r:0:0" and releases.next_token is None
    assert [item.title for item in releases.items] == ["Release 2.4.19", "Release 2.4.20"]
    notes = (await connector.fetch(releases.items[1])).data.decode()
    assert "OPS-1" in notes and "First paragraph of OPS-1." in notes
    version_searches = [request for request in seen if request["path"] == "/rest/api/3/search/jql"
                        and "fixVersion" in request["body"]["jql"]]
    assert version_searches, "release issues are searched on Cloud with search/jql"
    _only_cloud_requests(seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(("base_url", "token"), [(CLOUD, "3"), ("https://jira.example.test", "c:page-3")])
async def test_a_token_of_the_other_api_never_pages_on(base_url, token):
    seen: list[dict] = []
    connector = JiraConnector(_connection(base_url), project_keys=("OPS",), transport=_transport(seen))

    with pytest.raises(ConnectorError):
        await connector.list_items(token, limit=3)
    assert seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("bound", "complete"), [(2, False), (10, True)])
async def test_release_issue_completeness_comes_from_the_last_page(bound, complete):
    reader = SourceReader(_connection(), transport=_transport([]))

    issues, done = await search_release_issues(
        reader, release_jql("OPS", "20002", None), fields="summary,description", bound=bound, project_key="OPS"
    )

    # Version 20002 holds the odd fixture issues (OPS-1, 3, 5, 7).
    assert done is complete and [key for key, _ in issues] == ["OPS-1", "OPS-3", "OPS-5", "OPS-7"][:bound]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["cloud", "server"])
async def test_an_empty_page_while_more_remain_is_a_truncation(platform):
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path})
        if platform == "cloud":
            return httpx.Response(200, json={"issues": [], "nextPageToken": "page-0", "isLast": False})
        return httpx.Response(200, json={"issues": [], "startAt": 0, "maxResults": 10, "total": 4})

    base_url = CLOUD if platform == "cloud" else "https://jira.example.test"
    reader = SourceReader(_connection(base_url), transport=httpx.MockTransport(handler))

    issues, done = await search_release_issues(
        reader, release_jql("OPS", "20002", None), fields="summary", bound=10, project_key="OPS"
    )

    assert (issues, done) == ([], False) and len(seen) == 1, "reported truncated, and it never pages on"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    "/rest/api/2/issue",
    "/rest/api/2/issue/OPS-1/rest/api/3/search/jql",
    "/rest/api/3/search/jql/../../2/issue",
    "/rest/api/3/search/jqlx",
])
async def test_the_reader_refuses_any_other_post_before_it_is_sent(path):
    seen: list[dict] = []
    reader = SourceReader(_connection(), transport=_transport(seen))

    with pytest.raises(ConnectorError):
        await reader._request_json("POST", path, body={"fields": {}})
    assert seen == [], "nothing was sent"
    assert (await reader.post_search_jql({"jql": "project = OPS", "fields": ["summary"], "maxResults": 1}))["issues"]


def test_adf_bodies_render_as_text_and_wiki_text_is_unchanged():
    assert _body(text_to_adf("Line one\n\nLine two")) == "Line one\n\nLine two"
    assert _body("h1. Wiki *text*") == "h1. Wiki *text*"
    assert _body({"type": "not-adf"}) == "" and _body(42) == ""


KEPT = {"type": "text", "text": "kept"}


@pytest.mark.parametrize(("node", "expected"), [
    ({**KEPT, "marks": [{"type": "link", "attrs": "not-a-mapping"}]}, "kept"),
    ({**KEPT, "marks": [{"type": "link", "attrs": ["href"]}]}, "kept"),
    ({**KEPT, "marks": [{"type": "link", "attrs": {"href": {"nested": 1}}}]}, "kept"),
    ({**KEPT, "marks": 7}, "kept"),
    ({**KEPT, "marks": [None, "code", {"type": ["link"]}]}, "kept"),
    ({"type": ["text"], "content": [KEPT]}, "kept"),
    ({"type": {"text": 1}, "content": [KEPT]}, "kept"),
    ({"type": "text", "text": {"not": "text"}}, ""),
    ({"type": "mention", "attrs": "x", "content": 3}, ""),
    ({"type": "emoji", "attrs": {"text": 5, "shortName": ":ok:"}}, ":ok:"),
])
def test_a_malformed_adf_node_degrades_to_the_text_it_carries(node, expected):
    assert _body({"type": "doc", "content": [{"type": "paragraph", "content": [node]}]}) == expected


def test_an_issue_with_malformed_adf_bodies_still_renders():
    description = {"type": "doc", "content": [
        {"type": "heading", "attrs": {"level": True}, "content": "x"},
        {"type": "paragraph", "content": [{**KEPT, "marks": [{"type": "link", "attrs": "bad"}]}]},
    ]}
    rendered = render_issue("OPS-9", {"summary": "Broken body", "description": description,
                                      "comment": {"comments": [{"body": {"type": "doc", "content": 9}}]}})

    assert rendered.startswith("# OPS-9: Broken body") and "## Description\n\n# \n\nkept" in rendered
