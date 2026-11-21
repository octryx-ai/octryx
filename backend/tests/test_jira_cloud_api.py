"""Jira Cloud API: the real Jira tools and the secure_work sync against a Cloud-shaped stub.

The stub (``tests/fixtures/source_stubs/jira_stub_cloud.py``) refuses every Server/DC-only shape
(``/search`` is 410, plain-string bodies and ``name`` assignees are 400, ``username`` lookups are 400), so each
test proves the Cloud path, and every request the platform sent is recorded. Server/DC requests keep their
shapes (``/search`` with ``startAt``, wiki text, ``name``). No network: ``httpx.MockTransport`` only.
"""

from __future__ import annotations

import pytest

import app.tools.jira_impl._jira_query_search as search_module
from app.tools.jira_impl._jira_cloud import adf_to_text, is_jira_cloud, rich_text_body, text_to_adf
from app.tools.jira_impl._jira_query_search import SearchJiraTickets, SearchJiraUsers
from app.tools.jira_impl._jira_query_ticket_actions import AddJiraComment, GetJiraTicket
from app.tools.jira_impl._jira_ticket_tools import CreateJiraTicket, UpdateJiraTicket
from tests.jira_cloud_api_support import (  # noqa: F401
    CLOUD_URL,
    _cloud_config,
    _context,
    _no_server_only_request,
    cloud,
    cloud_stub,
)

# --- pure helpers ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("url", "config", "expected"), [
    ("https://your-site.atlassian.net", {}, True),
    ("https://EXAMPLE.Atlassian.NET/", {}, True),
    ("https://jira.example.com", {"jira_auth_mode": "cloud_api_token"}, True),
    ("https://jira.example.com", {"jira_auth_mode": "basic"}, False),
    ("https://jira.example.com", {}, False),
    ("https://atlassian.net.evil.example", {}, False),
])
def test_cloud_is_the_atlassian_host_or_the_cloud_auth_mode(url, config, expected):
    assert is_jira_cloud(url, config) is expected


def test_adf_round_trips_plain_text_and_reads_rich_documents():
    document = text_to_adf("First line\nsecond line\n\nNext paragraph")
    assert document["type"] == "doc" and document["version"] == 1 and len(document["content"]) == 2
    assert adf_to_text(document) == "First line\nsecond line\n\nNext paragraph"
    rich = {"type": "doc", "version": 1, "content": [
        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Plan"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "one"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "docs", "marks": [{"type": "link", "attrs": {"href": "https://x.test"}}]}]}]},
        ]},
        {"type": "paragraph", "content": [{"type": "mention", "attrs": {"text": "@Ada"}}]},
    ]}
    assert adf_to_text(rich) == "## Plan\n\n- one\n- [docs](https://x.test)\n\n@Ada"
    assert adf_to_text("wiki *text*") == "wiki *text*" and adf_to_text(None) == ""
    assert rich_text_body("wiki *text*", cloud=False) == "wiki *text*"


# --- tools on Jira Cloud --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_uses_search_jql_with_tokens_and_explicit_fields(cloud, monkeypatch):  # noqa: F811
    import app.tools.jira_impl._jira_cloud as cloud_module

    monkeypatch.setattr(cloud_module, "CLOUD_PAGE_SIZE", 2)
    result = await SearchJiraTickets().execute(
        {"jql": "project = OPS ORDER BY key ASC", "start_at": 3}, _context(_cloud_config())
    )

    # Cloud has no startAt: the offset is reached by walking the tokens of 2-issue pages.
    assert [item["ticket_id"] for item in result["results"]] == ["OPS-4", "OPS-5", "OPS-6", "OPS-7"]
    assert (result["api_version"], result["total"]) == ("3", None)
    searches = [request for request in cloud if request["path"] == "/rest/api/3/search/jql"]
    assert all(request["method"] == "POST" and "summary" in request["body"]["fields"] for request in searches)
    assert any(request["body"].get("nextPageToken") for request in searches), "the offset is reached by tokens"
    _no_server_only_request(cloud)


@pytest.mark.asyncio
async def test_a_ticket_reads_adf_description_and_comments_as_text(cloud):  # noqa: F811
    result = await GetJiraTicket().execute({"ticket_id": "OPS-2"}, _context(_cloud_config()))

    assert result["description"] == "First paragraph of OPS-2.\n\nSecond paragraph."
    assert result["comments"] == [{"author": "Alan Turing", "body": "Looks good to me.", "created": "2026-10-02T09:00:00.000+0000"}]
    _no_server_only_request(cloud)


@pytest.mark.asyncio
async def test_a_comment_is_sent_as_adf(cloud):  # noqa: F811
    result = await AddJiraComment().execute({"ticket_id": "OPS-2", "body": "Done\n\nShipped."}, _context(_cloud_config()))

    assert (result["status"], result["api_version"]) == ("comment_added", "3")
    [post] = [request for request in cloud if request["method"] == "POST"]
    assert post["body"]["body"] == text_to_adf("Done\n\nShipped.")


@pytest.mark.asyncio
async def test_an_agent_turn_comment_carries_the_ai_marker_in_the_adf_body(cloud):  # noqa: F811
    context = _context(_cloud_config())
    context.turn_model = "claude-haiku-5-5"
    await AddJiraComment().execute({"ticket_id": "OPS-2", "body": "Done"}, context)

    [post] = [request for request in cloud if request["method"] == "POST"]
    assert post["body"]["body"] == text_to_adf("Done\n\n— Written by AI (octryx · claude-haiku-5-5).")


@pytest.mark.asyncio
async def test_create_and_update_send_adf_and_an_account_id_never_a_name(cloud):  # noqa: F811
    created = await CreateJiraTicket().execute(
        {"project_key": "OPS", "summary": "New", "description": "Body text", "assignee": "ada lovelace"},
        _context(_cloud_config()),
    )
    assert created["ticket_id"] == "OPS-100"
    [create] = [request for request in cloud if request["method"] == "POST" and request["path"] == "/rest/api/3/issue"]
    assert create["body"]["fields"]["description"] == text_to_adf("Body text")
    assert create["body"]["fields"]["assignee"] == {"accountId": cloud_stub.USERS[0]["accountId"]}

    updated = await UpdateJiraTicket().execute(
        {"ticket_id": "OPS-2", "description": "Changed", "assignee": "alan@example.test"}, _context(_cloud_config())
    )
    assert updated["status"] == "updated"
    [put] = [request for request in cloud if request["method"] == "PUT"]
    assert put["body"]["fields"] == {"description": text_to_adf("Changed"),
                                     "assignee": {"accountId": cloud_stub.USERS[1]["accountId"]}}
    _no_server_only_request(cloud)


@pytest.mark.asyncio
@pytest.mark.parametrize("assignee", ["Nobody Known", "Ada", "ada"])
async def test_an_unresolved_cloud_assignee_is_refused_before_any_write(cloud, assignee):  # noqa: F811
    """Only an exact accountId, display name or email resolves: a prefix, even the lone search result, never does."""
    result = await CreateJiraTicket().execute(
        {"project_key": "OPS", "summary": "New", "assignee": assignee}, _context(_cloud_config())
    )

    assert "could not be resolved to exactly one Jira Cloud account" in result["error"]
    assert not [request for request in cloud if request["method"] in {"POST", "PUT"} and "/issue" in request["path"]]


@pytest.mark.asyncio
async def test_user_search_asks_only_the_cloud_query_endpoints(cloud):  # noqa: F811
    result = await SearchJiraUsers().execute({"query": "ada", "project_key": "OPS"}, _context(_cloud_config()))

    assert result["api_version"] == "3"
    assert [user["account_id"] for user in result["users"]] == [cloud_stub.USERS[0]["accountId"]]
    assert {request["path"] for request in cloud} <= {"/rest/api/3/user/assignable/search", "/rest/api/3/user/search"}
    _no_server_only_request(cloud)


@pytest.mark.asyncio
async def test_a_user_search_that_finds_nobody_never_falls_back_to_username(cloud):  # noqa: F811
    """Every Cloud endpoint is asked when nobody matches; none of them is a Server/DC ``username`` lookup."""
    result = await SearchJiraUsers().execute({"query": "zz-nobody", "project_key": "OPS"}, _context(_cloud_config()))

    assert (result["api_version"], result["users"]) == ("3", [])
    assert len(cloud) == 3, "assignable by query, global by query, assignable for the project"
    _no_server_only_request(cloud)


@pytest.mark.asyncio
async def test_a_release_bundle_with_an_unresolved_cloud_assignee_writes_nothing(cloud):  # noqa: F811
    from app.tools.jira_impl._jira_release_bundle import CreateJiraReleaseBundle

    result = await CreateJiraReleaseBundle().execute(
        {"project_key": "OPS", "release_name": "2.0", "tickets": [{"summary": "A", "assignee": "Nobody Known"}]},
        _context(_cloud_config()),
    )

    assert "nothing was created" in result["error"]
    assert not [request for request in cloud if request["method"] in {"POST", "PUT"}]


# --- real links on writes, one retry hint on an empty search -------------------------------------------------------


@pytest.mark.asyncio
async def test_t08_a_created_ticket_and_a_comment_name_their_real_issue_page(cloud):  # noqa: F811
    """Gemma wrote an invented demo-shop.atlassian.net link for the ticket it had just created (T08, T09)."""
    created = await CreateJiraTicket().execute({"project_key": "OPS", "summary": "New"}, _context(_cloud_config()))
    commented = await AddJiraComment().execute({"ticket_id": "OPS-2", "body": "Done"}, _context(_cloud_config()))

    assert created["url"] == f"{CLOUD_URL}/browse/OPS-100"
    assert commented["url"] == f"{CLOUD_URL}/browse/OPS-2"


@pytest.mark.asyncio
async def test_t05_an_empty_search_suggests_one_retry_with_a_single_keyword(cloud, monkeypatch):  # noqa: F811
    """Gemma searched once for "Vorratskammer Pantry", found nothing and stopped (T05)."""
    from app.tools.empty_search_hint import EMPTY_SEARCH_HINT

    found = await SearchJiraTickets().execute({"jql": "project = OPS ORDER BY key ASC"}, _context(_cloud_config()))
    # The stub ignores text filters: Jira answering no match is the allowlisted issue list coming back empty.
    monkeypatch.setattr(search_module, "allowed_issues", lambda *_args: [])
    empty = await SearchJiraTickets().execute({"jql": "project = OPS AND text ~ \"Vorratskammer Pantry\""},
                                              _context(_cloud_config()))

    assert empty["results"] == [] and empty["next_step"] == EMPTY_SEARCH_HINT
    assert found["results"] and "next_step" not in found
