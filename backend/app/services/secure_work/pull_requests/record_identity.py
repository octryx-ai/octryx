"""What a pull request record is: its identity, and the Workspace it belongs to."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import exists

from ....models import WorkItem, WorkPullRequest

IDENTITY_COLUMNS = ("provider", "provider_instance", "project_key", "repository_slug", "pr_id")


def web_host(url: Any) -> str:
    return urlparse(str(url or "").strip()).netloc.rsplit("@", 1)[-1].lower()


def identity_of(provider: Any, host: Any, repository: Any, number: Any) -> dict[str, str]:
    owner, _, name = str(repository or "").strip().strip("/").rpartition("/")
    return {"provider": str(provider or "").strip().lower(), "provider_instance": str(host or "").strip().lower(),
            "project_key": owner, "repository_slug": name, "pr_id": str(number or "").strip()}


def answered_pull_request(result: dict[str, Any]) -> tuple[str, str]:
    number = result.get("number") or result.get("iid") or result.get("id") or result.get("pr_id")
    url = (result.get("html_url") or result.get("web_url") or result.get("url") or result.get("pr_url")
           or result.get("links"))
    return str(number or "").strip(), (url.strip() if isinstance(url, str) else "")


def pull_request_identity(provider: str, pr_url: str, repository: str, number: Any) -> dict[str, str]:
    identity = identity_of(provider, web_host(pr_url), repository, number)
    if not all(identity.values()) or any(len(identity[column]) > getattr(WorkPullRequest, column).type.length
                                         for column in IDENTITY_COLUMNS):
        raise HTTPException(status_code=422, detail="The pull request's host, repository path or number is missing "
                                                    "or too long")
    return identity


def stored_identity(pull_request: Any) -> dict[str, str] | None:
    # A run that stored no identity never has its pull request read, matched or refreshed.
    identity = dict(pull_request or {}).get("identity")
    if not isinstance(identity, dict) or not all(
            isinstance(identity.get(column), str) and identity[column] for column in IDENTITY_COLUMNS):
        return None
    return {column: identity[column] for column in IDENTITY_COLUMNS}


def same_pull_request(left: Any, right: Any) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    parts = [(str(left.get(column) or "").strip().lower(), str(right.get(column) or "").strip().lower())
             for column in IDENTITY_COLUMNS]
    return all(mine and mine == theirs for mine, theirs in parts)


def in_item_workspace():
    # The record's Work Item must exist and lie in the record's own Workspace.
    return exists().where(WorkItem.id == WorkPullRequest.work_item_id, WorkItem.project_id == WorkPullRequest.scope_key)


__all__ = ["IDENTITY_COLUMNS", "answered_pull_request", "identity_of", "in_item_workspace", "pull_request_identity",
           "same_pull_request", "stored_identity", "web_host"]
