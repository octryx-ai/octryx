"""Jira discovery tools: project and version listing from the project context, user search and project metadata."""

from typing import Any

import pytest

from app.tools.context import ToolContext
from app.tools.definitions.jira import get_jira_definitions
from app.tools.jira_impl._jira_helpers_api import _jira_search_users_raw
from app.tools.jira_impl._jira_query_metadata import ListJiraIssueTypes, ListJiraPriorities
from app.tools.jira_impl._jira_query_search import SearchJiraUsers
from app.tools.jira_impl._jira_version_tools import ListJiraProjects, ListJiraVersions


def test_list_jira_versions_schema_uses_project_context_without_llm_project_key():
    definition = get_jira_definitions()["list_jira_versions"]
    parameters = definition["function"]["parameters"]

    assert parameters["properties"] == {}
    assert parameters["additionalProperties"] is False


def test_list_jira_projects_schema_is_read_only_scope_discovery():
    definition = get_jira_definitions()["list_jira_projects"]
    parameters = definition["function"]["parameters"]

    assert "project keys available" in definition["function"]["description"]
    assert parameters["properties"] == {}
    assert parameters["additionalProperties"] is False


@pytest.mark.asyncio
async def test_list_jira_projects_returns_configured_allowed_projects_without_guessing():
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_allowed_projects": ["ACME", "SHOP"],
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root="/tmp",
    )

    result = await ListJiraProjects().execute({}, context)

    assert result["source"] == "project_config"
    assert result["restricted"] is True
    # Each project names its /browse page on the configured Jira (E1 evidence fields).
    assert result["projects"] == [
        {
            "key": key,
            "allowed": True,
            "source_title": key,
            "source_url": f"https://jira.example.com/jira/browse/{key}",
            "cite_as": f"[{key}](https://jira.example.com/jira/browse/{key})",
        }
        for key in ("ACME", "SHOP")
    ]


@pytest.mark.asyncio
async def test_list_jira_versions_reads_all_allowed_projects_without_llm_project_key(monkeypatch):
    requested_paths: list[str] = []

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        del client, jira_url, headers, params
        requested_paths.append(path)
        project_key = path.split("/")[2]
        return [{"id": f"{project_key}-v1", "name": f"{project_key} 1.0", "released": False}], "3"

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)
    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_allowed_projects": ["ACME", "SHOP"],
        },
        capability_type="diagnosis",
        agent_mode_key="diagnosis",
        workspace_root="/tmp",
    )

    result = await ListJiraVersions().execute({}, context)

    assert requested_paths == ["/project/ACME/versions", "/project/SHOP/versions"]
    assert result["project_key"] is None
    assert result["project_keys"] == ["ACME", "SHOP"]
    assert [item["project_key"] for item in result["versions"]] == ["ACME", "SHOP"]


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_search_jira_users_and_project_metadata_tools(monkeypatch):
    async def fake_search_users(client, jira_url, *, headers, query, project_key, limit):
        assert query == "alice"
        assert project_key == "ACME"
        return (
            [
                {
                    "name": "alice",
                    "key": "JIRAUSER17330",
                    "displayName": "Alice Example",
                    "emailAddress": "alice@example.com",
                    "active": True,
                }
            ],
            "2",
        )

    async def fake_jira_api_get(client, jira_url, path, headers=None, params=None):
        if path == "/project/ACME":
            return {
                "issueTypes": [
                    {"id": "4", "name": "Improvement", "description": "Improve something", "subtask": False},
                    {"id": "1", "name": "Bug", "description": "Fix something", "subtask": False},
                ]
            }, "2"
        if path == "/priority":
            return [
                {"id": "1", "name": "Blocker", "description": "Top"},
                {"id": "3", "name": "Major", "description": "Major loss"},
            ], "2"
        raise AssertionError(path)

    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_search_users_raw", fake_search_users)
    monkeypatch.setattr("app.tools.jira_impl._jira_helpers_api._jira_api_get", fake_jira_api_get)

    context = ToolContext(
        user_id="u1",
        project_ids=[],
        roles=["admin"],
        session_id="s1",
        project_config={
            "jira_url": "https://jira.example.com/jira",
            "jira_username": "alice",
            "jira_password": "secret",
            "jira_allowed_projects": ["ACME"],
        },
        capability_type="change",
        agent_mode_key="change",
        workspace_root="/tmp",
    )

    users = await SearchJiraUsers().execute({"query": "alice"}, context)
    issue_types = await ListJiraIssueTypes().execute({"project_key": "ACME"}, context)
    priorities = await ListJiraPriorities().execute({}, context)

    assert users["users"][0]["name"] == "alice"
    assert issue_types["issue_types"][0]["name"] == "Improvement"
    assert priorities["priorities"][1]["name"] == "Major"


@pytest.mark.asyncio
async def test_search_jira_users_falls_back_to_project_user_roster_by_display_name():
    class FakeResponse:
        status_code = 200
        content = b"[]"

        def __init__(self, payload: list[dict[str, Any]]):
            self._payload = payload

        def json(self) -> list[dict[str, Any]]:
            return self._payload

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def get(self, url: str, *, headers: dict[str, str], params: dict[str, Any]) -> FakeResponse:
            del headers
            self.calls.append((url, params))
            if "username" in params or "query" in params:
                return FakeResponse([])
            return FakeResponse(
                [
                    {
                        "name": "alice",
                        "key": "JIRAUSER17330",
                        "displayName": "Alice Example",
                        "emailAddress": "alice@example.com",
                        "active": True,
                    },
                    {
                        "name": "someoneelse",
                        "displayName": "Someone Else",
                        "emailAddress": "someone@example.com",
                        "active": True,
                    },
                ]
            )

    client = FakeClient()

    users, api_version = await _jira_search_users_raw(
        client,
        "https://jira.example.com/jira",
        headers={},
        query="Alice Example",
        project_key="ACME",
        limit=10,
    )

    assert api_version == "2"
    assert users == [
        {
            "name": "alice",
            "key": "JIRAUSER17330",
            "displayName": "Alice Example",
            "emailAddress": "alice@example.com",
            "active": True,
        }
    ]
    assert client.calls[-1][1] == {"project": "ACME", "maxResults": 100}
