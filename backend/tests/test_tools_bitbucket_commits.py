"""The pull request update tool is a mutating connector tool, and the commit listing and user search tools return their results."""

from datetime import UTC
from typing import Any

import pytest

from app.tools.context import ToolContext
from app.tools.definitions import get_tool_definition_metadata
from app.tools.registry import execute_tool


def test_update_bitbucket_pull_request_is_mutating_bitbucket_connector_tool():
    metadata = get_tool_definition_metadata("update_bitbucket_pull_request")

    assert metadata.owner_type == "connector"
    assert metadata.connector == "bitbucket"
    assert metadata.mutates_state is True


@pytest.mark.asyncio
async def test_list_recent_bitbucket_commits_tool(monkeypatch):
    async def fake_get(context, path, params=None):
        if path.endswith("/branches/default"):
            return {"displayId": "main"}
        if path.endswith("/branches"):
            return {
                "values": [
                    {"displayId": "main"},
                    {"displayId": "release/prod"},
                ],
                "isLastPage": True,
            }
        assert "commits" in path
        path.split("/projects/")[1].split("/repos/")[0]
        repo_slug = path.split("/repos/")[1].split("/commits")[0]
        branch_name = (params or {}).get("until") or "main"
        now_ms = 1_700_000_000_000
        return {
            "values": [
                {
                    "id": f"{repo_slug}-{branch_name}-new",
                    "displayId": f"{repo_slug[:6]}123",
                    "message": f"Recent commit for {repo_slug} on {branch_name}",
                    "author": {"name": "tester", "emailAddress": "tester@example.com"},
                    "authorTimestamp": now_ms,
                },
                {
                    "id": f"{repo_slug}-{branch_name}-old",
                    "displayId": f"{repo_slug[:6]}999",
                    "message": f"Old commit for {repo_slug} on {branch_name}",
                    "author": {"name": "tester", "emailAddress": "tester@example.com"},
                    "authorTimestamp": now_ms - (10 * 24 * 60 * 60 * 1000),
                },
            ],
            "isLastPage": True,
        }

    class FrozenDateTime:
        @staticmethod
        def now(tz=None):
            from datetime import datetime

            return datetime.fromtimestamp(1_700_000_000, tz=UTC if tz else None)

        @staticmethod
        def fromtimestamp(value, tz=None):
            from datetime import datetime

            return datetime.fromtimestamp(value, tz=tz)

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_repository_commits.datetime", FrozenDateTime)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "bitbucket_url": "https://example.invalid/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-config", "enabled": True},
                {"project_key": "SHOP", "repo_slug": "acme-orders-access-ini", "enabled": True},
            ],
        },
    )

    result = await execute_tool("list_recent_bitbucket_commits", {"days": 5, "include_all_branches": True}, context)
    assert result["days"] == 5
    assert result["branch_mode"] == "all"
    assert result["total_commit_count"] == 4
    assert len(result["repositories"]) == 2
    assert result["commits"][0]["repo_slug"] in {"acme-orders-config", "acme-orders-access-ini"}
    assert all(commit["id"].endswith("-new") for commit in result["commits"])
    assert set(result["repositories"][0]["branches_scanned"]) == {"main", "release/prod"}


@pytest.mark.asyncio
async def test_search_bitbucket_users_tool(monkeypatch):
    observed: dict[str, Any] = {}

    async def fake_get(context, path, params=None):
        observed["path"] = path
        observed["params"] = params
        return {
            "values": [
                {
                    "name": "alice",
                    "displayName": "Alice Example",
                    "emailAddress": "alice@example.com",
                    "slug": "alice",
                    "active": True,
                }
            ]
        }

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "bitbucket_url": "https://example.invalid/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
        },
    )

    result = await execute_tool("search_bitbucket_users", {"query": "Alice Example"}, context)

    assert observed["path"] == "/rest/api/1.0/users"
    assert observed["params"] == {"filter": "Alice Example", "limit": 10}
    assert result["users"][0]["name"] == "alice"
    assert result["users"][0]["email_address"] == "alice@example.com"
