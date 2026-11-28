"""Shared SCM helpers for design delivery sync."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from ..secret import resolve_secret_refs
from ..tool_config import get_tool_config


def github_repo_from_remote(remote_url: str) -> tuple[str, str] | None:
    raw = str(remote_url or "").strip()
    if not raw:
        return None
    cleaned = raw
    if cleaned.startswith("git@github.com:"):
        cleaned = f"https://github.com/{cleaned.split(':', 1)[1]}"
    split = urlsplit(cleaned)
    parts = [part for part in split.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    owner = parts[-2]
    repo = parts[-1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return (owner, repo) if owner and repo else None


def bitbucket_repo_from_remote(remote_url: str) -> tuple[str, str] | None:
    raw = str(remote_url or "").strip()
    if not raw:
        return None
    cleaned = raw
    if "@" in cleaned and ":" in cleaned and "://" not in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    split = urlsplit(cleaned if "://" in cleaned else f"https://placeholder/{cleaned.lstrip('/')}")
    parts = [part for part in split.path.strip("/").split("/") if part]
    if len(parts) >= 3 and parts[-3].lower() == "scm":
        project_key = parts[-2]
        repo_slug = parts[-1]
    elif len(parts) >= 4 and parts[-4].lower() == "projects" and parts[-2].lower() == "repos":
        project_key = parts[-3]
        repo_slug = parts[-1]
    elif len(parts) >= 2:
        project_key = parts[-2]
        repo_slug = parts[-1]
    else:
        return None
    if repo_slug.endswith(".git"):
        repo_slug = repo_slug[:-4]
    return (project_key, repo_slug) if project_key and repo_slug else None


def gitlab_project_from_remote(remote_url: str) -> str | None:
    raw = str(remote_url or "").strip()
    if not raw:
        return None
    cleaned = raw
    if "@" in cleaned and ":" in cleaned and "://" not in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    split = urlsplit(cleaned if "://" in cleaned else f"https://placeholder/{cleaned.lstrip('/')}")
    parts = [part for part in split.path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None
    parts[-1] = parts[-1][:-4] if parts[-1].endswith(".git") else parts[-1]
    return "/".join(parts)


async def resolved_bitbucket_config(db: AsyncSession) -> dict[str, Any]:
    entry = await get_tool_config(db, "bitbucket", None)
    if entry is None or not entry.is_active:
        return {}
    return await resolve_secret_refs(db, dict(entry.config or {}), tool_name="bitbucket", project_id=None,
                                     purpose="design_delivery.scm_sync")


async def resolved_gitlab_config(db: AsyncSession) -> dict[str, Any]:
    entry = await get_tool_config(db, "gitlab", None)
    if entry is None or not entry.is_active:
        return {}
    return await resolve_secret_refs(db, dict(entry.config or {}), tool_name="gitlab", project_id=None,
                                     purpose="design_delivery.scm_sync")


def normalize_gitlab_base_url(config: dict[str, Any]) -> str:
    raw = str(config.get("gitlab_url") or "").strip().rstrip("/")
    if not raw:
        return ""
    return raw if raw.endswith("/api/v4") else raw + "/api/v4"


def gitlab_headers(config: dict[str, Any]) -> dict[str, str]:
    token = str(config.get("gitlab_token") or "").strip()
    return {"PRIVATE-TOKEN": token} if token else {}
