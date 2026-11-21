"""The GitHub connector service: its package surface, normalisation and repository listing."""

import httpx
import pytest
from fastapi import HTTPException

from app.models import BuiltInToolConfig
from app.services import github_connector as github_connector_service
from app.services.github_connector import service as github_connector_package_service
from app.services.repository_bootstrap.providers import github_api_base


def test_github_connector_package_exports_its_service_surface() -> None:
    exported_names = (
        "_github_headers",
        "_normalize_github_base_url",
        "_normalize_github_owner_type",
        "_resolved_github_config",
        "create_github_connector_repository",
        "list_github_connector_repositories",
    )

    for name in exported_names:
        assert getattr(github_connector_service, name) is getattr(github_connector_package_service, name)


def test_normalize_github_owner_type_contract_is_stable() -> None:
    assert github_connector_service._normalize_github_owner_type("user") == "user"
    assert github_connector_service._normalize_github_owner_type("personal") == "user"
    assert github_connector_service._normalize_github_owner_type("org") == "org"
    assert github_connector_service._normalize_github_owner_type("unexpected") == "org"


def test_normalize_github_base_url_accepts_public_web_url() -> None:
    assert github_connector_service._normalize_github_base_url({"github_url": "https://github.com"}) == (
        "https://api.github.com"
    )
    assert github_connector_service._normalize_github_base_url({"github_url": "https://www.github.com/"}) == (
        "https://api.github.com"
    )
    assert github_connector_service._normalize_github_base_url({"github_url": "https://api.github.com/"}) == (
        "https://api.github.com"
    )
    assert github_connector_service._normalize_github_base_url({"github_url": "https://ghe.example.com/api/v3"}) == (
        "https://ghe.example.com/api/v3"
    )
    assert github_api_base({"github_url": "https://github.com"}) == "https://api.github.com"


@pytest.mark.asyncio
async def test_list_github_connector_repositories_uses_authenticated_user_repos_for_user_owner(db, monkeypatch):
    db.add(
        BuiltInToolConfig(
            tool_name="github",
            project_id=None,
            is_active=True,
            config={
                "github_url": "https://github.com",
                "github_token": "gh-token",
                "github_owner": "alice-example",
                "github_owner_type": "user",
            },
        )
    )
    await db.commit()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            assert url == "https://api.github.com/user/repos"
            assert headers["Authorization"] == "Bearer gh-token"
            assert params["affiliation"] == "owner"
            assert params["visibility"] == "all"
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "alice-example/private-one",
                        "name": "private-one",
                        "private": True,
                        "default_branch": "main",
                        "html_url": "https://github.com/alice-example/private-one",
                        "clone_url": "https://github.com/alice-example/private-one.git",
                    }
                ],
                request=request,
            )

    monkeypatch.setattr(github_connector_package_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await github_connector_service.list_github_connector_repositories(db)

    assert result["count"] == 1
    assert result["items"][0]["full_name"] == "alice-example/private-one"
    assert result["items"][0]["private"] is True


@pytest.mark.asyncio
async def test_list_github_connector_repositories_blank_owner_type_uses_authenticated_repos(db, monkeypatch):
    db.add(
        BuiltInToolConfig(
            tool_name="github",
            project_id=None,
            is_active=True,
            config={
                "github_url": "https://github.com",
                "github_token": "gh-token",
                "github_owner": "alice-example",
                "github_owner_type": "",
            },
        )
    )
    await db.commit()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            assert url == "https://api.github.com/user/repos"
            assert headers["Authorization"] == "Bearer gh-token"
            assert params["affiliation"] == "owner,collaborator,organization_member"
            assert params["visibility"] == "all"
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(
                200,
                json=[
                    {
                        "full_name": "alice-example/private-one",
                        "name": "private-one",
                        "private": True,
                        "default_branch": "main",
                        "owner": {"login": "alice-example"},
                    },
                    {
                        "full_name": "other/shared-one",
                        "name": "shared-one",
                        "private": True,
                        "default_branch": "main",
                        "owner": {"login": "other"},
                    },
                ],
                request=request,
            )

    monkeypatch.setattr(github_connector_package_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await github_connector_service.list_github_connector_repositories(db)

    assert result["count"] == 1
    assert result["items"][0]["full_name"] == "alice-example/private-one"


@pytest.mark.asyncio
async def test_list_github_connector_repositories_paginates_org_repositories(db, monkeypatch):
    db.add(
        BuiltInToolConfig(
            tool_name="github",
            project_id=None,
            is_active=True,
            config={
                "github_url": "https://api.github.com",
                "github_token": "gh-token",
                "github_owner": "acme",
                "github_owner_type": "org",
            },
        )
    )
    await db.commit()
    seen_pages: list[int] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            assert url == "https://api.github.com/orgs/acme/repos"
            assert params["type"] == "all"
            page = int(params["page"])
            seen_pages.append(page)
            payload = [
                {
                    "full_name": f"acme/repo-{page}-{index}",
                    "name": f"repo-{page}-{index}",
                    "private": False,
                    "default_branch": "main",
                }
                for index in range(100 if page == 1 else 20)
            ]
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(200, json=payload, request=request)

    monkeypatch.setattr(github_connector_package_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    result = await github_connector_service.list_github_connector_repositories(db, limit=120)

    assert result["count"] == 120
    assert seen_pages == [1, 2]


@pytest.mark.asyncio
async def test_list_github_connector_repositories_translates_github_http_error(db, monkeypatch):
    db.add(
        BuiltInToolConfig(
            tool_name="github",
            project_id=None,
            is_active=True,
            config={
                "github_url": "https://api.github.com",
                "github_token": "gh-secret-token",
                "github_owner": "missing-org",
                "github_owner_type": "org",
            },
        )
    )
    await db.commit()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, params=None):
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(404, json={"message": "Not Found"}, request=request)

    monkeypatch.setattr(github_connector_package_service.httpx, "AsyncClient", lambda *args, **kwargs: FakeClient())

    with pytest.raises(HTTPException) as exc_info:
        await github_connector_service.list_github_connector_repositories(db)

    assert exc_info.value.status_code == 404
    assert "Could not list GitHub repositories" in str(exc_info.value.detail)
    assert "gh-secret-token" not in str(exc_info.value.detail)
