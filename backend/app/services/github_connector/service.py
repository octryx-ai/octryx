from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.outbound_egress import CONNECTION_GITHUB, egress_transport

from ..code_intelligence.repository import create_code_repository
from ..github_url import normalize_github_api_base_url
from ..repository_bootstrap import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_MESSAGE,
    create_github_repository,
    initialize_local_repository,
    safe_repo_name,
)
from ..secret import resolve_secret_refs
from ..tool_config import get_tool_config
from .repository_format import (
    _github_repository_matches_owner,
    _raise_for_github_status,
    _serialize_github_repository,
)


def _normalize_github_owner_type(value: Any) -> str:
    owner_type = str(value or "org").strip().lower() or "org"
    return "user" if owner_type in {"user", "personal"} else "org"


def _normalize_github_base_url(config: dict[str, Any]) -> str:
    return normalize_github_api_base_url(config.get("github_url"))


async def _resolved_github_config(db: AsyncSession) -> dict[str, Any]:
    entry = await get_tool_config(db, "github", None)
    if entry is None or not entry.is_active:
        raise HTTPException(status_code=400, detail="GitHub connector is not configured")
    config = dict(entry.config or {})
    resolved = await resolve_secret_refs(db, config, tool_name="github", project_id=None)
    token = str(resolved.get("github_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="GitHub connector token is missing")
    return resolved


def _github_headers(config: dict[str, Any]) -> dict[str, str]:
    token = str(config.get("github_token") or "").strip()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def list_github_connector_repositories(db: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    config = await _resolved_github_config(db)
    base_url = _normalize_github_base_url(config)
    owner = str(config.get("github_owner") or "").strip()
    owner_type = _normalize_github_owner_type(config.get("github_owner_type"))
    raw_owner_type = str(config.get("github_owner_type") or "").strip().lower()
    allowed = config.get("github_allowed_repositories") or []
    items: list[dict[str, Any]] = []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GITHUB)
    ) as client:
        if isinstance(allowed, list) and allowed:
            for raw_name in allowed[:limit]:
                full_name = str(raw_name or "").strip()
                if full_name and "/" not in full_name and owner:
                    full_name = f"{owner}/{full_name}"
                if not full_name:
                    continue
                response = await client.get(f"{base_url}/repos/{full_name}", headers=_github_headers(config))
                _raise_for_github_status(response, operation="load configured GitHub repository")
                data = response.json()
                items.append(_serialize_github_repository(data, fallback_full_name=full_name))
        else:
            endpoint, params, owner_filter = _github_repository_list_endpoint(
                base_url=base_url,
                owner=owner,
                owner_type=owner_type,
                raw_owner_type=raw_owner_type,
            )
            for repo in await _list_github_repositories_paginated(
                client,
                endpoint=endpoint,
                headers=_github_headers(config),
                params=params,
                limit=limit,
                owner_filter=owner_filter,
            ):
                items.append(_serialize_github_repository(repo))
    return {
        "count": len(items),
        "owner": owner,
        "items": items,
    }


def _github_repository_list_endpoint(
    *,
    base_url: str,
    owner: str,
    owner_type: str,
    raw_owner_type: str = "",
) -> tuple[str, dict[str, Any], str]:
    if owner and not raw_owner_type:
        return (
            f"{base_url}/user/repos",
            {"affiliation": "owner,collaborator,organization_member", "visibility": "all"},
            owner,
        )
    if owner and owner_type == "org":
        return f"{base_url}/orgs/{owner}/repos", {"type": "all"}, ""
    if owner and owner_type == "user":
        return f"{base_url}/user/repos", {"affiliation": "owner", "visibility": "all"}, owner
    return (
        f"{base_url}/user/repos",
        {"affiliation": "owner,collaborator,organization_member", "visibility": "all"},
        "",
    )


async def _list_github_repositories_paginated(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    headers: dict[str, str],
    params: dict[str, Any],
    limit: int,
    owner_filter: str = "",
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    items: list[dict[str, Any]] = []
    page = 1
    while len(items) < safe_limit:
        page_size = 100 if owner_filter else min(100, safe_limit - len(items))
        response = await client.get(
            endpoint,
            headers=headers,
            params={
                **params,
                "per_page": page_size,
                "sort": "updated",
                "page": page,
            },
        )
        _raise_for_github_status(response, operation="list GitHub repositories")
        page_items = response.json()
        if not isinstance(page_items, list) or not page_items:
            break
        for item in page_items:
            if not isinstance(item, dict) or not _github_repository_matches_owner(item, owner_filter):
                continue
            items.append(item)
            if len(items) >= safe_limit:
                break
        if len(page_items) < page_size:
            break
        page += 1
    return items


async def _bootstrap_local_repository(
    db: AsyncSession,
    payload: dict[str, Any],
    *,
    local_path_raw: str,
    repository_name: str,
    default_branch: str,
    description: str,
    remote: dict[str, Any],
    remote_git_env: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    code_repository: dict[str, Any] | None = None
    repo_path = Path(local_path_raw).expanduser().resolve()
    local_bootstrap = await initialize_local_repository(
        repo_path=repo_path,
        repo_name=repository_name,
        default_branch=default_branch,
        create_readme=bool(payload.get("create_readme", True)),
        create_gitignore=bool(payload.get("create_gitignore", True)),
        initial_commit=bool(payload.get("initial_commit", True)),
        initial_commit_message=str(payload.get("initial_commit_message") or DEFAULT_COMMIT_MESSAGE).strip()
        or DEFAULT_COMMIT_MESSAGE,
        remote_url=str(remote.get("clone_url") or "").strip() or None,
        timeout_sec=max(60, min(int(payload.get("timeout_sec") or 300), 1800)),
        **({"remote_git_env": remote_git_env} if remote_git_env else {}),
    )
    if local_bootstrap.get("error"):
        raise HTTPException(status_code=400, detail=str(local_bootstrap.get("error")))
    if bool(payload.get("register_code_repository")):
        code_repository = await create_code_repository(
            db,
            {
                "project_id": str(payload.get("project_id") or "").strip() or None,
                "name": repository_name,
                "description": description,
                "repo_root": str(repo_path),
                "provider": "github",
                "remote_url": str(remote.get("clone_url") or "").strip() or None,
                "default_branch": default_branch,
                "index_backend": str(payload.get("index_backend") or "auto"),
                "semantic_backend": str(payload.get("semantic_backend") or "auto"),
                "structure_backend": str(payload.get("structure_backend") or "auto"),
                "graph_backend": str(payload.get("graph_backend") or "auto"),
                "is_active": True,
                "config_json": {"source": "github_connector"},
            },
        )
    return local_bootstrap, code_repository


async def create_github_connector_repository(db: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    config = await _resolved_github_config(db)
    repository_name = safe_repo_name(payload.get("name") or payload.get("repository_name") or "")
    if not repository_name:
        raise HTTPException(status_code=400, detail="Repository name is required")
    default_branch = str(payload.get("default_branch") or DEFAULT_BRANCH).strip() or DEFAULT_BRANCH
    description = str(payload.get("description") or "").strip()
    visibility = str(payload.get("visibility") or "private").strip().lower() or "private"
    owner = str(payload.get("owner") or config.get("github_owner") or "").strip()
    owner_type = _normalize_github_owner_type(payload.get("owner_type") or config.get("github_owner_type"))

    remote = await create_github_repository(
        project_config=config,
        config={
            "github_owner": owner,
            "github_owner_type": owner_type,
            "remote_visibility": visibility,
        },
        repo_name=repository_name,
    )

    # The token's header for the initial push: never part of the answer, and never a token in a URL.
    remote_git_env = remote.pop("git_env", None)
    local_bootstrap: dict[str, Any] | None = None
    code_repository: dict[str, Any] | None = None
    local_path_raw = str(payload.get("local_path") or "").strip()
    if local_path_raw:
        local_bootstrap, code_repository = await _bootstrap_local_repository(
            db,
            payload,
            local_path_raw=local_path_raw,
            repository_name=repository_name,
            default_branch=default_branch,
            description=description,
            remote=remote,
            remote_git_env=remote_git_env,
        )

    return {
        "repository": {
            "name": repository_name,
            "description": description,
            "visibility": visibility,
            "owner": owner,
            "owner_type": owner_type,
            **remote,
        },
        "local_bootstrap": local_bootstrap,
        "code_repository": code_repository,
    }
