"""Bitbucket fetch helpers for design delivery sync."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import BITBUCKET

from ..connector_auth.atlassian import credential_auth, resolve_credential
from ..outbound_egress import CONNECTION_BITBUCKET, egress_transport
from .scm_common import resolved_bitbucket_config


def _auth(config: dict[str, Any]) -> httpx.Auth | None:
    credential = resolve_credential(BITBUCKET, config)
    return credential_auth(credential) if credential is not None else None


async def fetch_bitbucket_releases(
    db: AsyncSession,
    *,
    project_key: str,
    repo_slug: str,
    limit: int,
) -> list[dict[str, Any]]:
    config = await resolved_bitbucket_config(db)
    base_url = str(config.get("bitbucket_url") or "").strip().rstrip("/")
    auth = _auth(config)
    if not base_url or auth is None:
        return []
    async with httpx.AsyncClient(
        timeout=30, auth=auth, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)
    ) as client:
        response = await client.request(
            "GET",
            f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/tags",
            params={"limit": max(1, min(limit, 200))},
        )
        response.raise_for_status()
        payload = response.json()
    return [
        {
            "external_id": f"bitbucket-tag#{str(item.get('displayId') or item.get('id') or '')}",
            "title": str(item.get("displayId") or item.get("id") or ""),
            "body": str((item.get("latestCommit") or "") or ""),
            "url": "",
            "state": "completed",
            "tag_name": str(item.get("displayId") or item.get("id") or ""),
            "provider": "bitbucket",
            "repository_name": f"{project_key}/{repo_slug}",
            "object_kind": "tag",
            "number": None,
        }
        for item in (payload.get("values") or [])
        if str(item.get("displayId") or item.get("id") or "").strip()
    ]


async def fetch_bitbucket_checkpoints(
    db: AsyncSession,
    *,
    project_key: str,
    repo_slug: str,
    limit: int,
) -> list[dict[str, Any]]:
    config = await resolved_bitbucket_config(db)
    base_url = str(config.get("bitbucket_url") or "").strip().rstrip("/")
    auth = _auth(config)
    if not base_url or auth is None:
        return []
    async with httpx.AsyncClient(
        timeout=30, auth=auth, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)
    ) as client:
        response = await client.request(
            "GET",
            f"{base_url}/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/commits",
            params={"limit": max(1, min(limit, 100))},
        )
        response.raise_for_status()
        payload = response.json()
    return [
        {
            "external_id": f"bitbucket-commit#{str(item.get('id') or '')[:12]}",
            "title": str(item.get("message") or "Pipeline checkpoint").splitlines()[0][:240],
            "body": str(item.get("message") or ""),
            "url": "",
            "state": "completed",
            "provider": "bitbucket",
            "repository_name": f"{project_key}/{repo_slug}",
            "object_kind": "commit_checkpoint",
            "number": None,
            "branch": "",
            "head_sha": str(item.get("id") or ""),
            "event": "commit",
            "conclusion": "success",
        }
        for item in (payload.get("values") or [])
    ]
