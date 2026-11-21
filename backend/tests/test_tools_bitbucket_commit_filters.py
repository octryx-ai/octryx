"""Commit listing filters: author aliases, the default branch, the user's limit over the model's and a named ref."""

from datetime import UTC
from typing import Any

import pytest

from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
async def test_list_recent_bitbucket_commits_filters_by_author_aliases(monkeypatch):
    async def fake_get(context, path, params=None):
        if path.endswith("/branches/default"):
            return {"displayId": "main"}
        now_ms = 1_700_000_000_000
        return {
            "values": [
                {
                    "id": "lc-new",
                    "displayId": "lc123",
                    "message": "Acme Orders AWS fix",
                    "author": {"name": "alice", "emailAddress": "alice@example.com"},
                    "authorTimestamp": now_ms,
                },
                {
                    "id": "other-new",
                    "displayId": "zz999",
                    "message": "Unrelated",
                    "author": {"name": "other", "emailAddress": "other@example.com"},
                    "authorTimestamp": now_ms,
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
                {"project_key": "RIVER", "repo_slug": "service-config", "enabled": True},
            ],
        },
    )

    result = await execute_tool(
        "list_recent_bitbucket_commits",
        {"days": 5, "author_aliases": ["alice", "Alice Example"]},
        context,
    )

    assert result["author_filter"] == ["alice", "Alice Example"]
    assert result["total_commit_count"] == 1
    assert result["commits"][0]["id"] == "lc-new"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_recent_bitbucket_commits_defaults_to_default_branch_without_summary_or_gitops_context(monkeypatch):
    observed_commit_params: list[dict[str, Any] | None] = []

    async def fake_get(context, path, params=None):
        if path.endswith("/branches/default"):
            return {"displayId": "main"}
        if path.endswith("/branches"):
            raise AssertionError("full branch listing should not be used in default-branch mode")
        observed_commit_params.append(params)
        return {"values": [], "isLastPage": True}

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        current_user_message="Zeige mir die letzten Commits im Repo.",
        project_config={
            "bitbucket_url": "https://example.invalid/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-config", "enabled": True},
            ],
        },
    )

    result = await execute_tool("list_recent_bitbucket_commits", {"days": 5}, context)

    assert result["branch_mode"] == "selected"
    assert observed_commit_params[0]["until"] == "main"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_recent_bitbucket_commits_ignores_model_limit_without_user_limit(monkeypatch):
    observed: list[dict[str, Any] | None] = []

    async def fake_get(context, path, params=None):
        if path.endswith("/branches/default"):
            return {"displayId": "main"}
        if path.endswith("/branches"):
            return {"values": [{"displayId": "main"}, {"displayId": "release/prod"}], "isLastPage": True}
        observed.append(params)
        return {"values": [], "isLastPage": True}

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
        current_user_message="Erstelle eine Wochenzusammenfassung aus Jira, Bitbucket und Confluence.",
        project_config={
            "bitbucket_url": "https://example.invalid/bitbucket",
            "bitbucket_username": "user",
            "bitbucket_password": "secret",
            "bitbucket_allowed_repos": [
                {"project_key": "SHOP", "repo_slug": "acme-orders-config", "enabled": True},
            ],
        },
    )

    await execute_tool("list_recent_bitbucket_commits", {"days": 5, "per_repo_limit": 20}, context)
    assert observed[0] == {"limit": 100, "start": 0, "until": "main"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("params", "until"), [({}, "main"), ({"ref": "feature/x"}, "feature/x")])
async def test_list_bitbucket_commits_reads_the_default_branch_unless_a_ref_is_named(monkeypatch, params, until):
    """"The latest commits" must not mix in feature-branch commits; the default branch answers."""
    calls: list[tuple[str, dict]] = []

    async def fake_get(context, path, params=None):
        calls.append((path, dict(params or {})))
        if path.endswith("/branches/default"):
            return {"displayId": "main"}
        return {"values": []}

    monkeypatch.setattr("app.tools.bitbucket_impl._bitbucket_internal_network._bitbucket_json_get", fake_get)
    context = ToolContext(
        user_id="test", project_ids=[], roles=["viewer"], session_id="test",
        project_config={
            "bitbucket_url": "https://bitbucket.example.com",
            "bitbucket_allowed_repos": [{"project_key": "CHEF", "repo_slug": "kitchen-helper-mini", "enabled": True}],
        },
    )
    result = await execute_tool("list_bitbucket_commits", {"project_key": "CHEF", "repo_slug": "kitchen-helper-mini", **params},
                                context)

    commit_calls = [query for path, query in calls if path.endswith("/commits")]
    assert commit_calls == [{"limit": 100, "until": until}] and result["ref"] == until
