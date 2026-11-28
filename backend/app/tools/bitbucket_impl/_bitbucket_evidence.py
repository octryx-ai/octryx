"""Bitbucket (Server/Data Center) read results as evidence: each item names its openable source."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..evidence_fields import item_url, with_source


def repo_url(base: str, project_key: str, repo_slug: str) -> str | None:
    return item_url(base, "projects", project_key, "repos", repo_slug, "browse")


def file_url(base: str, project_key: str, repo_slug: str, path: str, ref: str | None) -> str | None:
    query = f"at={quote(ref, safe='')}" if ref else ""
    return item_url(base, "projects", project_key, "repos", repo_slug, "browse", path, query=query)


def with_repo_source(item: dict[str, Any], base: str) -> dict[str, Any]:
    key, slug = str(item.get("project_key") or ""), str(item.get("repo_slug") or "")
    return with_source(item, title=item.get("label") or f"{key}/{slug}", url=repo_url(base, key, slug))


def with_branch_source(item: dict[str, Any], base: str, project_key: str, repo_slug: str) -> dict[str, Any]:
    name = str(item.get("name") or "")
    query = f"at={quote(f'refs/heads/{name}', safe='')}"
    url = item_url(base, "projects", project_key, "repos", repo_slug, "browse", query=query) if name else None
    return with_source(item, title=f"{project_key}/{repo_slug}@{name}", url=url)


def with_entry_source(
    item: dict[str, Any], base: str, project_key: str, repo_slug: str, ref: str | None
) -> dict[str, Any]:
    path = str(item.get("path") or "")
    url = file_url(base, project_key, repo_slug, path, ref) if path else None
    return with_source(item, title=f"{project_key}/{repo_slug}: {path}", url=url)


def with_pull_request_source(item: dict[str, Any], base: str, project_key: str, repo_slug: str) -> dict[str, Any]:
    pr_id = str(item.get("id") or "")
    url = item_url(base, "projects", project_key, "repos", repo_slug, "pull-requests", pr_id)
    return with_source(item, title=f"{project_key}/{repo_slug} PR #{pr_id}: {item.get('title') or ''}", url=url)


def with_commit_source(item: dict[str, Any], base: str, project_key: str, repo_slug: str) -> dict[str, Any]:
    commit_id = str(item.get("commit_id") or item.get("id") or "")
    url = item_url(base, "projects", project_key, "repos", repo_slug, "commits", commit_id)
    label = item.get("display_id") or commit_id[:12]
    return with_source(item, title=f"{project_key}/{repo_slug}@{label}", url=url)


__all__ = [
    "file_url",
    "repo_url",
    "with_branch_source",
    "with_commit_source",
    "with_entry_source",
    "with_pull_request_source",
    "with_repo_source",
]
