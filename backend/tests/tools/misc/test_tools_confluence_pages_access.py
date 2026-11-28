"""The page allowlist is authoritative over the space allowlist, and the Confluence tools respect space and page rules."""

import json

import pytest

from app.tools._confluence_access import page_allowed
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


def test_confluence_page_allowlist_is_authoritative_over_space_allowlist():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
            "confluence_allowed_pages": [{"id": "123", "space_key": "ENG", "enabled": True}],
        },
    )

    assert page_allowed(context, page_id="123", space_key="ENG") is True
    assert page_allowed(context, page_id="789", space_key="ENG") is False


def test_confluence_page_access_falls_back_to_space_when_no_page_allowlist_exists():
    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
        },
    )

    assert page_allowed(context, page_id="789", space_key="ENG") is True


def _page_payloads():
    return {
        "123": {
            "id": "123",
            "title": "Runbook",
            "space": {"key": "ENG"},
            "body": {"storage": {"value": "<p>ok</p>"}},
            "version": {"number": 3},
            "ancestors": [],
        },
        "124": {
            "id": "124",
            "title": "Runbook Child",
            "space": {"key": "ENG"},
            "body": {"storage": {"value": "<p>child</p>"}},
            "version": {"number": 2},
            "ancestors": [{"id": "123"}],
        },
        "456": {"id": "456", "title": "Draft", "space": {"key": "ENG"}, "version": {"number": 1}},
        "789": {
            "id": "789",
            "title": "Other Same-Space Page",
            "space": {"key": "ENG"},
            "body": {"storage": {"value": "<p>should be denied</p>"}},
            "version": {"number": 1},
            "ancestors": [],
        },
    }


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
        if "/descendant/page" in url:
            return FakeResponse(
                {
                    "results": [
                        {"id": "124", "title": "Runbook Child", "space": {"key": "ENG"}, "type": "page",
                         "ancestors": [{"id": "123"}]},
                        {"id": "456", "title": "Draft", "space": {"key": "ENG"}, "type": "page",
                         "ancestors": [{"id": "123"}]},
                    ]
                }
            )
        if "/rest/api/content/" in url:
            page_id = url.rstrip("/").split("/")[-1]
            return FakeResponse(_page_payloads()[page_id])
        if url.endswith("/rest/api/content"):
            if params.get("title") == "Runbook":
                return FakeResponse({"results": [_page_payloads()["123"]]})
            if params.get("title") == "Runbook Child":
                return FakeResponse({"results": [_page_payloads()["124"]]})
            return FakeResponse(
                {
                    "results": [
                        {"id": "123", "title": "Runbook", "space": {"key": "ENG"}, "type": "page"},
                        {"id": "456", "title": "Draft", "space": {"key": "ENG"}, "type": "page"},
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")


def _page_rules_context():
    return ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "confluence_url": "https://wiki.example.com/wiki",
            "confluence_username": "alice",
            "confluence_password": "secret",
            "confluence_allowed_spaces": [{"space_key": "ENG", "enabled": True}],
            "confluence_allowed_pages": [
                {"id": "123", "title": "Runbook", "space_key": "ENG", "enabled": True, "include_children": True},
                {"id": "456", "title": "Draft", "space_key": "ENG", "enabled": False},
            ],
        },
    )


@pytest.mark.asyncio
async def test_confluence_tools_respect_space_and_page_rules(monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", lambda *args, **kwargs: FakeClient())

    context = _page_rules_context()
    listed = await execute_tool("list_confluence_pages", {"space_key": "ENG"}, context)
    assert len(listed["pages"]) == 2
    assert listed["pages"][0]["title"] == "Runbook"
    assert any(page["title"] == "Runbook Child" for page in listed["pages"])

    listed_with_versions = await execute_tool(
        "list_confluence_pages",
        {"space_key": "ENG", "include_versions": True},
        context,
    )
    child = next(page for page in listed_with_versions["pages"] if page["id"] == "124")
    assert child["version"] == 2

    page = await execute_tool("get_confluence_page", {"title": "Runbook", "space_key": "ENG"}, context)
    assert page["id"] == "123"
    assert "<p>ok</p>" in page["content"]

    child_page = await execute_tool("get_confluence_page", {"title": "Runbook Child", "space_key": "ENG"}, context)
    assert child_page["id"] == "124"
    assert "<p>child</p>" in child_page["content"]

    denied_same_space_page = await execute_tool("get_confluence_page", {"page_id": "789"}, context)
    assert denied_same_space_page["error"] == "Confluence page Other Same-Space Page is not allowed for this project"
