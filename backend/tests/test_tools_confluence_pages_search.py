"""Search injects the space before ORDER BY in user CQL, a non-numeric page id is a title, and the knowledge builder ignores a too-small root limit."""

import json

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_search_confluence_injects_space_before_order_by_for_user_cql(monkeypatch):
    observed: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

        def __init__(self, payload):
            self.payload = payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, **kwargs):
            observed["url"] = url
            observed.setdefault("calls", []).append({"url": url, "params": params})
            if url.endswith("/child/page"):
                return FakeResponse(
                    {
                        "results": [
                            {
                                "id": "124",
                                "title": "Acme Orders AWS Child",
                                "space": {"key": "ENG"},
                                "version": {
                                    "number": 2,
                                    "when": "2026-06-02T10:00:00.000+0200",
                                    "by": {"username": "alice", "displayName": "Alice Example"},
                                },
                            }
                        ]
                    }
                )
            observed["params"] = params
            return FakeResponse(
                {
                    "results": [
                        {
                            "id": "123",
                            "title": "Acme Orders AWS Runbook",
                            "space": {"key": "ENG"},
                            "version": {
                                "number": 4,
                                "when": "2026-06-01T10:00:00.000+0200",
                                "by": {"username": "alice", "displayName": "Alice Example"},
                            },
                        }
                    ]
                }
            )

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_url": "https://wiki.example/wiki",
            "confluence_username": "alice",
            "confluence_password": "secret",
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        },
    )

    result = await execute_tool(
        "search_confluence",
        {
            "cql": '(creator = "alice" OR contributor = "alice") AND type = page ORDER BY lastmodified DESC',
            "limit": 10,
            "include_child_summary": True,
            "child_limit": 3,
        },
        context,
    )

    assert observed["params"]["cql"] == (
        'space in ("ENG") AND ((creator = "alice" OR contributor = "alice") AND type = page) '
        "ORDER BY lastmodified DESC"
    )
    assert result["results"][0]["updated_by"]["display_name"] == "Alice Example"
    assert result["results"][0]["child_count"] == 1
    assert result["results"][0]["children"][0]["title"] == "Acme Orders AWS Child"
    assert result["results"][0]["children"][0]["updated_by"]["display_name"] == "Alice Example"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_get_confluence_page_treats_nonnumeric_page_id_as_title(monkeypatch):
    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload
            self.text = json.dumps(payload)

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, headers=None, auth=None):
            if url.endswith("/rest/api/content"):
                assert params["title"] == "Report Builder configuration"
                return FakeResponse(
                    {
                        "results": [
                            {
                                "id": "100106",
                                "title": "Report Builder configuration",
                                "space": {"key": "INFRA"},
                                "body": {"storage": {"value": "<p>configuration body</p>"}},
                                "version": {"number": 5},
                                "ancestors": [],
                            }
                        ]
                    }
                )
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_url": "https://wiki.example.com/wiki",
            "confluence_username": "alice",
            "confluence_password": "secret",
            "confluence_allowed_spaces": [{"space_key": "INFRA", "enabled": True}],
        },
    )

    page = await execute_tool(
        "get_confluence_page",
        {"page_id": "Report Builder configuration", "space_key": "INFRA"},
        context,
    )

    assert page["id"] == "100106"
    assert page["title"] == "Report Builder configuration"
    assert "<p>configuration body</p>" in page["content"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_knowledge_builder_context_ignores_too_small_root_limit(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def json(self):
            return self._payload

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, params=None, headers=None, auth=None):
            params = params or {}
            if url.endswith("/rest/api/content/100101"):
                return FakeResponse(
                    {
                        "id": "100101",
                        "title": "Knowledge sharing within the Acme Orders team",
                        "space": {"key": "INFRA"},
                        "type": "page",
                        "version": {"number": 5},
                    }
                )
            if url.endswith("/rest/api/content/100101/descendant/page"):
                start = int(params.get("start") or 0)
                if start == 0:
                    return FakeResponse(
                        {
                            "results": [
                                {
                                    "id": "1",
                                    "title": "Page 1",
                                    "space": {"key": "INFRA"},
                                    "type": "page",
                                    "version": {"number": 1},
                                },
                            ],
                            "size": 1,
                            "_links": {"next": "/rest/api/content/100101/descendant/page?start=1"},
                        }
                    )
                if start == 1:
                    return FakeResponse(
                        {
                            "results": [
                                {
                                    "id": "2",
                                    "title": "Page 2",
                                    "space": {"key": "INFRA"},
                                    "type": "page",
                                    "version": {"number": 1},
                                },
                            ],
                            "size": 1,
                            "_links": {},
                        }
                    )
            raise AssertionError(f"Unexpected URL/params: {url} {params}")

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_url": "https://wiki.example.com/wiki",
            "confluence_space_key": "INFRA",
            "confluence_root_page_id": "100101",
        },
        agent_definition={
            "name": "Acme Orders Knowledge Builder",
            "goal": "Build the project knowledge map from Confluence",
        },
    )

    result = await execute_tool("list_confluence_pages", {"limit": 1, "include_versions": True}, context)
    assert [page["id"] for page in result["pages"]] == ["100101", "1", "2"]
