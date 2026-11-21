"""Listing pages stops at the allowed page limit, starts from the root page without explicit allowlists and paginates descendants."""

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_list_confluence_pages_does_not_fetch_descendants_when_allowed_page_limit_is_met(monkeypatch):
    observed_urls: list[str] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

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
            observed_urls.append(url)
            if url.endswith("/rest/api/content/123"):
                return FakeResponse(
                    {
                        "id": "123",
                        "title": "Runbook",
                        "space": {"key": "ENG"},
                        "type": "page",
                        "version": {"number": 7},
                    }
                )
            if "/descendant/page" in url:
                raise AssertionError("descendants should not be fetched when the allowed page limit is already met")
            raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_url": "https://wiki.example.com/wiki",
            "confluence_allowed_pages": [
                {"id": "123", "title": "Runbook", "space_key": "ENG", "enabled": True, "include_children": True}
            ],
        },
    )

    listed = await execute_tool(
        "list_confluence_pages",
        {"limit": 1, "include_versions": True, "force_requested_limits": True},
        context,
    )

    assert listed["pages"] == [
        {
            "id": "123",
            "title": "Runbook",
            "space_key": "ENG",
            "enabled": True,
            "include_children": True,
            "version": 7,
            # Each listed page names its viewpage link on the configured Confluence (E1 evidence fields).
            "source_title": "Runbook",
            "source_url": "https://wiki.example.com/wiki/pages/viewpage.action?pageId=123",
            "cite_as": "[Runbook](https://wiki.example.com/wiki/pages/viewpage.action?pageId=123)",
        }
    ]
    assert observed_urls == ["https://wiki.example.com/wiki/rest/api/content/123"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_confluence_pages_uses_root_page_id_without_explicit_allowlists(monkeypatch):
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
                return FakeResponse(
                    {
                        "results": [
                            {
                                "id": "100102",
                                "title": "AWS - Acme Orders",
                                "space": {"key": "INFRA"},
                                "type": "page",
                                "version": {"number": 1},
                            },
                            {
                                "id": "100103",
                                "title": "AWS - Acme Orders Application Deployment",
                                "space": {"key": "INFRA"},
                                "type": "page",
                                "version": {"number": 18},
                            },
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
            "confluence_space_key": "INFRA",
            "confluence_root_page_id": "100101",
        },
    )

    result = await execute_tool("list_confluence_pages", {"limit": 10, "include_versions": True}, context)
    assert result["root_page_id"] == "100101"
    assert result["listing_complete"] is True
    assert [page["id"] for page in result["pages"]] == ["100101", "100102", "100103"]
    assert result["pages"][0]["title"] == "Knowledge sharing within the Acme Orders team"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_confluence_pages_paginates_descendants_from_root(monkeypatch):
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
                                {
                                    "id": "2",
                                    "title": "Page 2",
                                    "space": {"key": "INFRA"},
                                    "type": "page",
                                    "version": {"number": 1},
                                },
                            ],
                            "size": 2,
                            "_links": {"next": "/rest/api/content/100101/descendant/page?start=2"},
                        }
                    )
                if start == 2:
                    return FakeResponse(
                        {
                            "results": [
                                {
                                    "id": "3",
                                    "title": "Page 3",
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
    )

    result = await execute_tool("list_confluence_pages", {"limit": 10, "include_versions": True}, context)
    assert result["listing_complete"] is True
    assert [page["id"] for page in result["pages"]] == ["100101", "1", "2", "3"]
