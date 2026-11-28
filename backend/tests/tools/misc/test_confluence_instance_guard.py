"""The Confluence tools stay on the confirmed instance and connection (``tools/_confluence_instance``)."""

from __future__ import annotations

import httpx
import pytest

import app.tools._confluence_access as confluence_access
from app.tools._confluence_instance import (
    EXPECTED_CONNECTION_PARAM,
    EXPECTED_INSTANCE_PARAM,
    confluence_instance,
    connection_refusal,
    instance_refusal,
    url_on_instance,
)
from app.tools.confluence import CreateConfluencePage, GetConfluencePage, UpdateConfluencePage
from app.tools.context import ToolContext

BASE = "https://wiki.example.test/wiki"
INSTANCE = "https://wiki.example.test/wiki"
OTHER = "https://other.example.test/wiki"


@pytest.mark.parametrize(("url", "instance"), [
    ("https://Wiki.Example.Test/wiki/", "https://wiki.example.test/wiki"),
    ("https://wiki.example.test:443/wiki", "https://wiki.example.test/wiki"),
    ("http://wiki.example.test:80", "http://wiki.example.test"),
    ("https://wiki.example.test:8443/wiki", "https://wiki.example.test:8443/wiki"),
    ("https://user:pw@wiki.example.test/wiki?x=1#y", "https://wiki.example.test/wiki"),
    ("ftp://wiki.example.test/wiki", ""),
    ("wiki.example.test/wiki", ""),
    ("https://wiki.example.test:notaport/wiki", ""),
    ("", ""),
    (None, ""),
])
def test_the_instance_is_the_normalized_base_url_without_credentials(url, instance):
    assert confluence_instance(url) == instance


def test_a_call_without_an_expected_instance_is_not_refused():
    assert instance_refusal({}, BASE) is None
    assert instance_refusal({EXPECTED_INSTANCE_PARAM: "  "}, BASE) is None


def test_the_same_instance_in_another_spelling_is_not_refused():
    assert instance_refusal({EXPECTED_INSTANCE_PARAM: INSTANCE}, "https://WIKI.example.test:443/wiki/") is None


@pytest.mark.parametrize("serving", [OTHER, "https://wiki.example.test/confluence", "not a url"])
def test_another_instance_is_refused_with_a_409(serving):
    refused = instance_refusal({EXPECTED_INSTANCE_PARAM: INSTANCE}, serving)
    assert refused is not None
    assert (refused["status_code"], refused["instance_mismatch"]) == (409, True)
    assert refused["instance"] == confluence_instance(serving)
    assert refused["error"].startswith("instance_mismatch:")


def test_the_connection_is_pinned_by_id_and_the_default_entry_is_named_default():
    context = ToolContext(user_id="u", project_ids=[], roles=["viewer"], session_id="s", project_config={})
    assert connection_refusal({}, context) is None
    assert connection_refusal({EXPECTED_CONNECTION_PARAM: "default"}, context) is None
    context.connection_id = "docs-b"
    refused = connection_refusal({EXPECTED_CONNECTION_PARAM: "docs-a"}, context)
    assert refused is not None
    assert (refused["status_code"], refused["connection_mismatch"], refused["connection_id"]) == (409, True, "docs-b")
    assert connection_refusal({EXPECTED_CONNECTION_PARAM: "docs-b"}, context) is None


@pytest.mark.parametrize(("url", "on_instance"), [
    (f"{INSTANCE}/spaces/DOC/pages/901", True),
    (f"{INSTANCE}?pageId=901", True),
    ("https://wiki.example.test/wikis/DOC/pages/901", False),
    (f"{OTHER}/spaces/DOC/pages/901", False),
    ("https://wiki.example.test:8443/wiki/spaces/DOC", False),
])
def test_a_page_link_lies_on_an_instance_only_under_its_base_path(url, on_instance):
    assert url_on_instance(url, INSTANCE) is on_instance
    assert url_on_instance(url, "") is False


def _context(connection_id: str | None = None) -> ToolContext:
    context = ToolContext(user_id="u", project_ids=[], roles=["admin"], session_id="s", project_config={
        "confluence_url": BASE, "confluence_auth_mode": "basic",
        "confluence_username": "docs-bot", "confluence_password": "docs-pw",
        "confluence_allowed_spaces": [{"space_key": "DOC", "enabled": True}],
    })
    context.connection_id = connection_id
    return context


@pytest.fixture
def requests_sent(monkeypatch) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, json={"message": "unavailable"})

    monkeypatch.setattr(confluence_access, "egress_transport", lambda _connection: httpx.MockTransport(answer))
    return sent


_CALLS = [
    (GetConfluencePage, {"page_id": "901"}),
    (CreateConfluencePage, {"space_key": "DOC", "title": "Feature", "content": "<p>x</p>", "parent_id": "900"}),
    (UpdateConfluencePage, {"page_id": "901", "content": "<p>x</p>"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "params"), _CALLS)
async def test_another_instance_is_refused_before_any_request(requests_sent, tool, params):
    result = await tool().execute({**params, EXPECTED_INSTANCE_PARAM: OTHER}, _context())
    assert (result["status_code"], result.get("instance_mismatch")) == (409, True)
    assert result["instance"] == INSTANCE
    assert requests_sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "params"), _CALLS)
async def test_another_connection_on_the_same_instance_is_refused_before_any_request(requests_sent, tool, params):
    pinned = {**params, EXPECTED_INSTANCE_PARAM: INSTANCE, EXPECTED_CONNECTION_PARAM: "docs-a"}
    result = await tool().execute(pinned, _context(connection_id="docs-b"))
    assert (result["status_code"], result.get("connection_mismatch")) == (409, True)
    assert requests_sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool", "params"), _CALLS)
async def test_the_confirmed_instance_and_connection_reach_confluence(requests_sent, tool, params):
    pinned = {**params, EXPECTED_INSTANCE_PARAM: INSTANCE, EXPECTED_CONNECTION_PARAM: "docs-a"}
    try:
        result = await tool().execute(pinned, _context(connection_id="docs-a"))
    except httpx.HTTPStatusError:
        result = {}  # the stand-in Confluence answers 503; the tool registry turns that into a tool error
    assert not result.get("instance_mismatch") and not result.get("connection_mismatch")
    assert requests_sent, "a pinned call on the confirmed instance and connection is sent"
    assert all(str(request.url).startswith(BASE) for request in requests_sent)
