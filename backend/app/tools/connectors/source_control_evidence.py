"""GitHub and GitLab read results as evidence: each item names its openable source."""

from __future__ import annotations

from typing import Any

from ...services.github_url import github_web_base_url
from ..context import ToolContext
from ..evidence_fields import item_url, known_web_url, with_source
from .common import _string


def github_web_base(context: ToolContext) -> str | None:
    return github_web_base_url(context.project_config.get("github_url"))


def gitlab_web_base(context: ToolContext) -> str | None:
    raw = _string(context.project_config.get("gitlab_url")).rstrip("/")
    base = raw[: -len("/api/v4")] if raw.endswith("/api/v4") else raw
    return base or None


def with_github_item_source(
    item: dict[str, Any], web_base: str | None, owner: str, repo: str, kind: str, *, label: str
) -> dict[str, Any]:
    number = str(item.get("number") or "")
    url = item_url(web_base, owner, repo, kind, number) if web_base else None
    return with_source(item, title=f"{owner}/{repo} {label} #{number}: {item.get('title') or ''}", url=url)


def with_github_repository_source(item: dict[str, Any], web_base: str | None) -> dict[str, Any]:
    full_name = str(item.get("full_name") or "")
    url = item_url(web_base, full_name) if web_base and full_name.count("/") == 1 else None
    return with_source(item, title=full_name, url=url)


def with_github_branch_source(item: dict[str, Any], web_base: str | None, owner: str, repo: str) -> dict[str, Any]:
    name = str(item.get("name") or "")
    url = item_url(web_base, owner, repo, "tree", name) if web_base and name else None
    return with_source(item, title=f"{owner}/{repo}@{name}", url=url)


def with_web_url_source(item: dict[str, Any], web_base: str | None, *, url_field: str, title: str) -> dict[str, Any]:
    return with_source(item, title=title, url=known_web_url(item.get(url_field), web_base) if web_base else None)


__all__ = [
    "github_web_base",
    "gitlab_web_base",
    "with_github_branch_source",
    "with_github_item_source",
    "with_github_repository_source",
    "with_web_url_source",
]
