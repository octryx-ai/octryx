"""The repository's own Git token for a Bitbucket Server/Data Center Git command.

Data Center answers 500 on Git over HTTPS (``/scm/...``) for the OpenID Connect client credentials token, so a
workflow run's clone, fetch, pull or push fails with the connection's sign-in. A Workspace may register the
repository with its own Bitbucket HTTP access token (``services/knowledge/sources/repository_git_token.py``):
:func:`repository_git_token` answers it for the remote when exactly one Workspace is in play (the session's, else
the context's only one) and the remote is a repository on the connection's own instance; else ``None`` and Git
signs in with the connection. REST calls never use it. The token is never logged or returned to a caller
other than the Git environment builder (``_bitbucket_internal_core._bitbucket_git_auth_env_async``).
"""

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
    """The Workspace's own Git token for the Data Center repository at ``remote_url``, else ``None``."""
    db = getattr(context, "db", None)
    workspace = _workspace(context)
    if db is None or workspace is None:
        return None
    base = str((context.project_config or {}).get("bitbucket_url") or "").strip().rstrip("/")
    return await usable_git_token(db, workspace, identity_of_remote(remote_url, base))


__all__ = ["repository_git_token"]
