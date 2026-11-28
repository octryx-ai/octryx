"""GitHub repository listing and creation tools and the GitHub connector health check."""

from pathlib import Path

import pytest

from app.services import connector_test_service as connector_test_service_module
from app.services.connector_test_service import run_connector_connection_test
from app.tools.context import ToolContext
from app.tools.registry import execute_tool


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_list_github_repositories_tool_with_allowlist(monkeypatch):
    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert connection == "github"  # the GitHub egress rule, not the private-network one (#S8)
        assert method == "GET"
        assert headers["Authorization"] == "Bearer gh-token"
        if url.endswith("/repos/example/octryx"):
            return {
                "full_name": "example/octryx",
                "private": True,
                "default_branch": "main",
                "html_url": "https://github.com/example/octryx",
            }
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "github_token": "gh-token",
            "github_allowed_repositories": ["example/octryx"],
        },
    )
    result = await execute_tool("list_github_repositories", {"limit": 10}, context)
    assert result["count"] == 1
    assert result["repositories"][0]["full_name"] == "example/octryx"


@pytest.mark.asyncio
async def test_list_github_repositories_tool_uses_authenticated_user_repositories(monkeypatch):
    seen: list[tuple[str, dict]] = []

    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert url == "https://api.github.com/user/repos"
        assert headers["Authorization"] == "Bearer gh-token"
        seen.append((url, params or {}))
        return [
            {
                "full_name": "alice-example/private-one",
                "private": True,
                "default_branch": "main",
                "html_url": "https://github.com/alice-example/private-one",
            }
        ]

    monkeypatch.setattr("app.tools.connectors.common._http_json", fake_http_json)

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["viewer"],
        session_id="test",
        project_config={
            "github_url": "https://github.com",
            "github_token": "gh-token",
            "github_owner": "alice-example",
            "github_owner_type": "user",
        },
    )
    result = await execute_tool("list_github_repositories", {"limit": 10}, context)
    assert result["count"] == 1
    assert result["repositories"][0]["full_name"] == "alice-example/private-one"
    assert seen[0][1]["affiliation"] == "owner"
    assert seen[0][1]["visibility"] == "all"


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_create_github_repository_tool_bootstraps_workspace(monkeypatch, tmp_path: Path):
    async def fake_create_github_repository(*, project_config, config, repo_name):
        assert repo_name == "platform-api"
        assert config["github_owner"] == "example"
        return {
            "provider": "github",
            "repository_name": repo_name,
            "full_name": f"example/{repo_name}",
            "html_url": f"https://github.com/example/{repo_name}",
            "clone_url": f"https://github.com/example/{repo_name}.git",
            "git_env": {"GIT_CONFIG_VALUE_1": "Authorization: Basic gh-token-header"},
        }

    init_calls: list[dict] = []

    async def fake_initialize_local_repository(**kwargs):
        init_calls.append(kwargs)
        repo_path = kwargs["repo_path"]
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / ".git").mkdir()
        return {"initialized": True, "commit_created": True, "written_files": [], "head_commit": "abc123"}

    monkeypatch.setattr(
        "app.tools.connectors.github_repository_create.create_github_repository", fake_create_github_repository
    )
    monkeypatch.setattr(
        "app.tools.connectors.github_repository_create.initialize_local_repository", fake_initialize_local_repository
    )

    context = ToolContext(
        user_id="test",
        project_ids=[],
        roles=["admin"],
        session_id="test",
            project_config={
                "github_token": "gh-token",
                "github_owner": "example",
                "github_owner_type": "org",
                "tool_policy": {"allowlist": ["create_github_repository"]},
            },
            workspace_root=str(tmp_path),
        )
    result = await execute_tool(
        "create_github_repository",
        {"name": "platform-api", "local_path": "repos/platform-api"},
        context,
    )
    assert result["provider"] == "github"
    assert result["repository"]["full_name"] == "example/platform-api"
    assert result["local_bootstrap"]["initialized"] is True
    assert (tmp_path / "repos" / "platform-api" / ".git").exists()
    # The token travels only as the push's header, never in the remote URL or the answer.
    assert init_calls[0]["remote_url"] == "https://github.com/example/platform-api.git"
    assert init_calls[0]["remote_git_env"] == {"GIT_CONFIG_VALUE_1": "Authorization: Basic gh-token-header"}
    assert "gh-token" not in str(result) and "git_env" not in result["repository"]


@pytest.mark.asyncio
async def test_github_connector_health_normalizes_public_web_url(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"login": "alice-example"}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            assert url == "https://api.github.com/user"
            assert headers["Authorization"] == "Bearer gh-token"
            assert headers["Accept"] == "application/vnd.github+json"
            return FakeResponse()

    monkeypatch.setattr(connector_test_service_module.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await run_connector_connection_test(
        "github",
        {
            "github_url": "https://github.com",
            "github_token": "gh-token",
            "github_owner": "alice-example",
        },
    )

    assert result["ok"] is True
    assert result["summary"] == "Connected to GitHub."
    assert "alice-example" not in str(result)
    assert "api.github.com" not in str(result)
