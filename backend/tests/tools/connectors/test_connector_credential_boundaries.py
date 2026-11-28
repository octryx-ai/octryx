import pytest

from app.services.secret import set_secret_value
from app.services.tool_config import merge_tool_configs_into_project_config, upsert_tool_config
from app.tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_credentials_async
from app.tools.connectors.credential_boundary import connector_secret_value
from app.tools.connectors.github import ListGitHubRepositoriesTool
from app.tools.context import ToolContext


@pytest.mark.asyncio
async def test_git_connector_project_config_merge_keeps_secret_refs(db):
    github_secret = await set_secret_value(
        db,
        tool_name="github",
        field_name="github_token",
        project_id=None,
        value="gh-token",
    )
    gitlab_secret = await set_secret_value(
        db,
        tool_name="gitlab",
        field_name="gitlab_token",
        project_id=None,
        value="gl-token",
    )
    bitbucket_secret = await set_secret_value(
        db,
        tool_name="bitbucket",
        field_name="bitbucket_password",
        project_id=None,
        value="bb-password",
    )
    await upsert_tool_config(
        db,
        tool_name="github",
        project_id=None,
        config={
            "github_url": "https://api.github.com",
            "github_owner": "sample",
            "github_token_secret_ref": github_secret.id,
        },
        is_active=True,
    )
    await upsert_tool_config(
        db,
        tool_name="gitlab",
        project_id=None,
        config={
            "gitlab_url": "https://gitlab.example.com",
            "gitlab_group": "sample",
            "gitlab_token_secret_ref": gitlab_secret.id,
        },
        is_active=True,
    )
    await upsert_tool_config(
        db,
        tool_name="bitbucket",
        project_id=None,
        config={
            "bitbucket_url": "https://bitbucket.example.com",
            "bitbucket_auth_mode": "bearer_pat",
            "bitbucket_token_secret_ref": bitbucket_secret.id,
            "bitbucket_allowed_repos": [{"project_key": "OCX", "repo_slug": "backend"}],
        },
        is_active=True,
    )
    await db.commit()

    merged = await merge_tool_configs_into_project_config(db, None, {})

    assert "github_token" not in merged
    assert "gitlab_token" not in merged
    assert "bitbucket_token" not in merged
    assert merged["github_token_secret_ref"] == github_secret.id
    assert merged["gitlab_token_secret_ref"] == gitlab_secret.id
    assert merged["bitbucket_token_secret_ref"] == bitbucket_secret.id


@pytest.mark.asyncio
async def test_connector_secret_value_resolves_ref_inside_connector_boundary(db):
    secret = await set_secret_value(
        db,
        tool_name="github",
        field_name="github_token",
        project_id=None,
        value="gh-token",
    )
    await db.commit()
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["viewer"],
        session_id="session-1",
        project_config={"github_token_secret_ref": secret.id},
        db=db,
    )

    assert await connector_secret_value(context, connector_name="github", field_name="github_token") == "gh-token"


@pytest.mark.asyncio
async def test_bitbucket_credentials_resolve_refs_inside_connector_boundary(db):
    secret = await set_secret_value(
        db,
        tool_name="bitbucket",
        field_name="bitbucket_password",
        project_id=None,
        value="bb-password",
    )
    await db.commit()
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["viewer"],
        session_id="session-1",
        project_config={
            "bitbucket_auth_mode": "basic",
            "bitbucket_username": "agent",
            "bitbucket_password_secret_ref": secret.id,
        },
        db=db,
    )

    assert await _bitbucket_credentials_async(context) == ("agent", "bb-password")


@pytest.mark.asyncio
async def test_github_connector_uses_ref_based_token_without_raw_project_config(monkeypatch, db):
    secret = await set_secret_value(
        db,
        tool_name="github",
        field_name="github_token",
        project_id=None,
        value="gh-token",
    )
    await db.commit()

    async def fake_http_json(method, url, *, headers=None, params=None, json_body=None, timeout=30, connection=None):
        assert method == "GET"
        assert url == "https://api.github.com/repos/sample/repo"
        assert headers["Authorization"] == "Bearer gh-token"
        return {
            "full_name": "sample/repo",
            "private": True,
            "default_branch": "main",
            "html_url": "https://github.com/sample/repo",
        }

    monkeypatch.setattr("app.tools.connectors.github._http_json", fake_http_json)
    context = ToolContext(
        user_id="user-1",
        project_ids=[],
        roles=["viewer"],
        session_id="session-1",
        project_config={
            "github_url": "https://api.github.com",
            "github_owner": "sample",
            "github_allowed_repositories": ["sample/repo"],
            "github_token_secret_ref": secret.id,
        },
        db=db,
    )

    result = await ListGitHubRepositoriesTool().execute({}, context)

    assert result["repositories"] == [
        {
            "full_name": "sample/repo",
            "private": True,
            "default_branch": "main",
            "html_url": "https://github.com/sample/repo",
            # The repository names its page on the configured GitHub web host (E1 evidence fields).
            "source_title": "sample/repo",
            "source_url": "https://github.com/sample/repo",
            "cite_as": "[sample/repo](https://github.com/sample/repo)",
        }
    ]
    assert "github_token" not in context.project_config
