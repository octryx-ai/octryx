"""The read-only gate of the Bitbucket write paths: a repository the Workspace registered ``read_only`` is never written
through a Bitbucket connection."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from app.tools.context import ToolContext

from ...services.knowledge.sources.repository_access import (
    CLOUD_BASE,
    REASON_REPOSITORY_READ_ONLY,
    RepositoryIdentity,
    identity_of,
    identity_of_remote,
    repository_access_mode,
)
from ...services.knowledge.sources.sync.git_config import ACCESS_READ_ONLY, ACCESS_READ_WRITE
from ...services.named_connections.route_plan import refusal
from ._bitbucket_cloud import cloud_context

READ_ONLY_MESSAGE = ("This repository is registered read-only in this Workspace: the agent may not write to it "
                     "(branch, commit, push, pull request or comment).")
_SERVER_REPOSITORY = re.compile(r"^/rest/[^/]+/[^/]+/(?:projects/([^/?#]+)|users/([^/?#]+))/repos/([^/?#]+)")
_CLOUD_REPOSITORY = re.compile(r"^/repositories/([^/?#]+)/([^/?#]+)")


class RepositoryWriteRefusedError(Exception):
    def __init__(self, refused: dict[str, Any]) -> None:
        super().__init__(str(refused.get("error") or READ_ONLY_MESSAGE))
        self.refusal = refused


def _base_url(context: ToolContext) -> str:
    if cloud_context(context):
        return CLOUD_BASE
    return str((context.project_config or {}).get("bitbucket_url") or "").strip().rstrip("/")


def _workspaces(context: ToolContext) -> list[str]:
    session_workspace = str((context.project_config or {}).get("project_id") or "").strip()
    if session_workspace:
        return [session_workspace]
    return list(dict.fromkeys(str(item or "").strip() for item in context.project_ids or [] if str(item or "").strip()))


async def _read_only(context: ToolContext, identity: RepositoryIdentity) -> bool:
    modes = {await repository_access_mode(context.db, workspace, identity) for workspace in _workspaces(context)}
    return ACCESS_READ_ONLY in modes and ACCESS_READ_WRITE not in modes


def _refusal(identity: RepositoryIdentity) -> dict[str, Any]:
    project_key, _, repo_slug = identity.path.partition("/")
    return refusal(REASON_REPOSITORY_READ_ONLY, "bitbucket", READ_ONLY_MESSAGE, project_key=project_key,
                   repo_slug=repo_slug)


async def bitbucket_write_refusal(
    context: ToolContext,
    *,
    project_key: str | None = None,
    repo_slug: str | None = None,
    remote_urls: list[str] | tuple[str, ...] = (),
) -> dict[str, Any] | None:
    if getattr(context, "db", None) is None:
        return None
    base_url = _base_url(context)
    identities = [identity_of(base_url, project_key, repo_slug)] if project_key or repo_slug else []
    identities += [identity_of_remote(url, base_url) for url in remote_urls if str(url or "").strip()]
    for identity in dict.fromkeys(item for item in identities if item is not None):
        if await _read_only(context, identity):
            return _refusal(identity)
    return None


async def require_rest_write_allowed(context: ToolContext, method: str, path: str) -> None:
    if str(method or "").upper() in {"GET", "HEAD"}:
        return
    if match := _SERVER_REPOSITORY.match(str(path or "")):
        project_key = match[1] or f"~{match[2]}"
        repo_slug = match[3]
    elif match := _CLOUD_REPOSITORY.match(str(path or "")):
        project_key, repo_slug = match[1], match[2]
    else:
        return
    refused = await bitbucket_write_refusal(context, project_key=unquote(project_key), repo_slug=unquote(repo_slug))
    if refused is not None:
        raise RepositoryWriteRefusedError(refused)


__all__ = [
    "READ_ONLY_MESSAGE",
    "RepositoryWriteRefusedError",
    "bitbucket_write_refusal",
    "require_rest_write_allowed",
]
