"""The repository's own Git token for a Bitbucket Server/Data Center Git command."""

from __future__ import annotations

from app.tools.context import ToolContext

from ...services.knowledge.sources.repository_access import identity_of_remote
from ...services.knowledge.sources.repository_git_token import usable_git_token


def _workspace(context: ToolContext) -> str | None:
    session_workspace = str((context.project_config or {}).get("project_id") or "").strip()
    if session_workspace:
        return session_workspace
    workspaces = list(dict.fromkeys(str(item or "").strip() for item in context.project_ids or []
                                    if str(item or "").strip()))
    return workspaces[0] if len(workspaces) == 1 else None


async def repository_git_token(context: ToolContext, remote_url: str) -> str | None:
    db = getattr(context, "db", None)
    workspace = _workspace(context)
    if db is None or workspace is None:
        return None
    base = str((context.project_config or {}).get("bitbucket_url") or "").strip().rstrip("/")
    return await usable_git_token(db, workspace, identity_of_remote(remote_url, base))


__all__ = ["repository_git_token"]
