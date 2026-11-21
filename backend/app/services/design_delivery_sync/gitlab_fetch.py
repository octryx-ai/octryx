"""GitLab fetch helpers for design delivery sync."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..outbound_egress import CONNECTION_GITLAB, egress_transport
from .scm_common import gitlab_headers, normalize_gitlab_base_url, resolved_gitlab_config


async def fetch_gitlab_releases(db: AsyncSession, *, project_path: str, limit: int) -> list[dict[str, Any]]:
    config = await resolved_gitlab_config(db)
    base_url = normalize_gitlab_base_url(config)
    if not base_url:
        return []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GITLAB)
    ) as client:
        response = await client.request(
            "GET",
            f"{base_url}/projects/{project_path}/releases",
            headers=gitlab_headers(config),
            params={"per_page": max(1, min(limit, 100))},
        )
        response.raise_for_status()
        payload = response.json()
    return [
        {
            "external_id": f"gitlab-release#{item.get('tag_name')}",
            "title": str(item.get("name") or item.get("tag_name") or ""),
            "body": str(item.get("description") or ""),
            "url": str(item.get("_links", {}).get("self") or ""),
            "state": "completed",
            "tag_name": item.get("tag_name"),
            "provider": "gitlab",
            "repository_name": project_path,
            "object_kind": "release",
            "number": item.get("tag_name"),
        }
        for item in (payload or [])[:limit]
    ]


async def fetch_gitlab_checkpoints(db: AsyncSession, *, project_path: str, limit: int) -> list[dict[str, Any]]:
    config = await resolved_gitlab_config(db)
    base_url = normalize_gitlab_base_url(config)
    if not base_url:
        return []
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_GITLAB)
    ) as client:
        response = await client.request(
            "GET",
            f"{base_url}/projects/{project_path}/pipelines",
            headers=gitlab_headers(config),
            params={"per_page": max(1, min(limit, 100))},
        )
        response.raise_for_status()
        payload = response.json()
    return [
        {
            "external_id": f"gitlab-pipeline#{item.get('id')}",
            "title": f"Pipeline {item.get('id')}",
            "body": str(item.get("name") or ""),
            "url": str(item.get("web_url") or ""),
            "state": (
                "completed" if str(item.get("status") or "").lower() in {"success", "failed", "canceled"} else "active"
            ),
            "provider": "gitlab",
            "repository_name": project_path,
            "object_kind": "pipeline",
            "number": item.get("id"),
            "branch": item.get("ref"),
            "head_sha": item.get("sha"),
            "event": "",
            "conclusion": item.get("status"),
        }
        for item in (payload or [])[:limit]
    ]
