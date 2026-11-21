"""What a pull request record is: its identity, and the Workspace it belongs to.

Identity: the host the pull request lives on (``provider_instance``, the host of the URL the provider answered with),
the repository's full path (``project_key`` = owner/project/group path, ``repository_slug`` = repository name) and the
number, per ``provider``. It is derived once when the pull request is opened (``workflow_runs/platform/pr_details``,
``coding/coding_pr_delivery``), stored on the run (``run.pull_request["identity"]``) and as the record's identity
columns. Every later use takes that stored value (:func:`stored_identity`), never a re-derived one: the run's refresh
looks the record up by it, the refresh worker, the watch poll and the succession adoption read the pull request only
through a connection on the recorded host (``host_target.connection_host``), and a webhook event or a revert matches a
run only with the same host, path and number (:func:`same_pull_request`; the event's host is that of the pull request
URL in its signed payload).

Workspace: a record belongs to the Workspace of its Work Item, which is also its ``scope_key``
(:func:`in_item_workspace`); every reader and the writer select records through it.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import exists

from ....models import WorkItem, WorkPullRequest

IDENTITY_COLUMNS = ("provider", "provider_instance", "project_key", "repository_slug", "pr_id")


def web_host(url: Any) -> str:
    """The host (and port) of an absolute URL, lower case; ``""`` for anything else."""
    return urlparse(str(url or "").strip()).netloc.rsplit("@", 1)[-1].lower()


def identity_of(provider: Any, host: Any, repository: Any, number: Any) -> dict[str, str]:
    """The identity parts of pull request ``number`` on ``host`` of ``repository`` (``<owner path>/<name>``)."""
    owner, _, name = str(repository or "").strip().strip("/").rpartition("/")
    return {"provider": str(provider or "").strip().lower(), "provider_instance": str(host or "").strip().lower(),
            "project_key": owner, "repository_slug": name, "pr_id": str(number or "").strip()}


def answered_pull_request(result: dict[str, Any]) -> tuple[str, str]:
    """``(number, web URL)`` of the pull request a create tool answered with; ``""`` for a part it lacks.

    GitHub answers ``number`` and ``html_url``, GitLab ``iid`` and ``web_url``, Bitbucket Server only ``id`` and
    ``links`` (the pull request's web URL as a string), Bitbucket Cloud ``id``, ``url`` and ``links``."""
    number = result.get("number") or result.get("iid") or result.get("id") or result.get("pr_id")
    url = (result.get("html_url") or result.get("web_url") or result.get("url") or result.get("pr_url")
           or result.get("links"))
    return str(number or "").strip(), (url.strip() if isinstance(url, str) else "")


def pull_request_identity(provider: str, pr_url: str, repository: str, number: Any) -> dict[str, str]:
    """The identity of the pull request ``number`` opened on ``repository`` whose web URL the provider answered with
    ``pr_url``; 422 when a part is missing or longer than its column."""
    identity = identity_of(provider, web_host(pr_url), repository, number)
    if not all(identity.values()) or any(len(identity[column]) > getattr(WorkPullRequest, column).type.length
                                         for column in IDENTITY_COLUMNS):
        raise HTTPException(status_code=422, detail="The pull request's host, repository path or number is missing "
                                                    "or too long")
    return identity


def stored_identity(pull_request: Any) -> dict[str, str] | None:
    """The identity a run stored when it opened or adopted its pull request (``run.pull_request["identity"]``);
    ``None`` when it stored none: that run's pull request is then never read, matched or refreshed."""
    identity = dict(pull_request or {}).get("identity")
    if not isinstance(identity, dict) or not all(
            isinstance(identity.get(column), str) and identity[column] for column in IDENTITY_COLUMNS):
        return None
    return {column: identity[column] for column in IDENTITY_COLUMNS}


def same_pull_request(left: Any, right: Any) -> bool:
    """Both name one pull request: every identity part present on both and equal (ignoring case)."""
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    parts = [(str(left.get(column) or "").strip().lower(), str(right.get(column) or "").strip().lower())
             for column in IDENTITY_COLUMNS]
    return all(mine and mine == theirs for mine, theirs in parts)


def in_item_workspace():
    """The condition on ``WorkPullRequest`` rows: the record's Work Item exists and its Workspace is the record's
    ``scope_key``."""
    return exists().where(WorkItem.id == WorkPullRequest.work_item_id, WorkItem.project_id == WorkPullRequest.scope_key)


__all__ = ["IDENTITY_COLUMNS", "answered_pull_request", "identity_of", "in_item_workspace", "pull_request_identity",
           "same_pull_request", "stored_identity", "web_host"]
