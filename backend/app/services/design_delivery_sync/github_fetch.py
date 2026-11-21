"""GitHub fetch helpers for design delivery sync."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..github_connector import _github_headers, _normalize_github_base_url, _resolved_github_config
from ..outbound_egress import CONNECTION_GITHUB, egress_transport


async def fetch_github_releases(db: AsyncSession, *, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
    config = await _resolved_github_config(db)
    base_url = _normalize_github_base_url(config)
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GITHUB)
    ) as client:
        releases_response = await client.request(
            "GET",
            f"{base_url}/repos/{owner}/{repo}/releases",
            headers=_github_headers(config),
            params={"per_page": max(1, min(limit, 100))},
        )
        releases_response.raise_for_status()
        releases_payload = releases_response.json()
        tags_response = await client.request(
            "GET",
            f"{base_url}/repos/{owner}/{repo}/tags",
            headers=_github_headers(config),
            params={"per_page": max(1, min(limit, 100))},
        )
        tags_response.raise_for_status()
        tags_payload = tags_response.json()
    releases = [
        {
            "external_id": f"github-release#{item.get('id')}",
            "title": str(item.get("name") or item.get("tag_name") or ""),
            "body": str(item.get("body") or ""),
            "url": str(item.get("html_url") or ""),
            "state": "completed",
            "tag_name": str(item.get("tag_name") or ""),
            "provider": "github",
            "repository_name": f"{owner}/{repo}",
            "object_kind": "release",
            "number": item.get("id"),
        }
        for item in releases_payload or []
    ]
    existing_tag_names = {str(item.get("tag_name") or "").strip() for item in releases if item.get("tag_name")}
    tags = []
    for item in tags_payload or []:
        tag_name = str(item.get("name") or "").strip()
        if not tag_name or tag_name in existing_tag_names:
            continue
        tags.append(
            {
                "external_id": f"github-tag#{tag_name}",
                "title": tag_name,
                "body": "",
                "url": f"https://github.com/{owner}/{repo}/tree/{tag_name}",
                "state": "completed",
                "tag_name": tag_name,
                "provider": "github",
                "repository_name": f"{owner}/{repo}",
                "object_kind": "tag",
                "number": None,
            }
        )
    return [*releases, *tags]


async def fetch_github_checkpoints(db: AsyncSession, *, owner: str, repo: str, limit: int) -> list[dict[str, Any]]:
    config = await _resolved_github_config(db)
    base_url = _normalize_github_base_url(config)
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GITHUB)
    ) as client:
        response = await client.request(
            "GET",
            f"{base_url}/repos/{owner}/{repo}/actions/runs",
            headers=_github_headers(config),
            params={"per_page": max(1, min(limit, 100))},
        )
        response.raise_for_status()
        payload = response.json()
    runs = payload.get("workflow_runs") or []
    return [
        {
            "external_id": f"github-workflow#{item.get('id')}",
            "title": str(item.get("name") or item.get("display_title") or "Workflow run"),
            "body": f"{item.get('event') or ''} {item.get('head_branch') or ''}".strip(),
            "url": str(item.get("html_url") or ""),
            "state": (
                "completed"
                if str(item.get("status") or "").lower() == "completed"
                else str(item.get("status") or "active").lower()
            ),
            "provider": "github",
            "repository_name": f"{owner}/{repo}",
            "object_kind": "workflow_run",
            "number": item.get("run_number"),
            "branch": str(item.get("head_branch") or ""),
            "head_sha": str(item.get("head_sha") or ""),
            "event": str(item.get("event") or ""),
            "conclusion": (str(item.get("conclusion") or "")),
        }
        for item in runs
    ]
