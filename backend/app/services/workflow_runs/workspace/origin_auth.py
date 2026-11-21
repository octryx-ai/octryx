"""The Git credential a server working copy's ``origin`` is fetched with.

The server prepare (``server_prepare.py``) fetches the run's branch and its work in progress from ``origin``. Without
a credential a private Bitbucket Data Center repository refuses both fetches and every server-side run would stop
there. So the fetches get exactly the environment the Bitbucket tools clone and push with
(``tools/bitbucket_impl._bitbucket_git_auth_env_async``): the repository's own Git token when the Workspace set one
(``knowledge/sources/repository_git_token.py``), else the connection's sign-in — a Bearer token as
``http.<origin>/.extraHeader`` through ``GIT_CONFIG_*`` (``services/git_http_auth.bearer_header_env``), a Basic
sign-in through the askpass environment. Never in argv, the remote URL or a file.

The connection is the one the Bitbucket tools would use for the run's repository: the same route plan over the
Workspace's configuration (``named_connections/tool_routing.routed_execute``) with the run's requester as the tool
context (``platform/dispatch.tool_context``). The credential goes only to that connection's host
(``_require_connection_host``): a working copy whose ``origin`` points elsewhere gets nothing.

``None`` — fetch without a credential — for another provider (GitHub, GitLab), a working copy without an
``origin`` over HTTP(S), or a connection that cannot give one (refused route, incomplete sign-in). The reason is
logged as a fixed sentence; no URL, token or Git output is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .. import safe_git

logger = logging.getLogger(__name__)


async def origin_git_env(db: AsyncSession, run: WorkflowRun, root: Path | str) -> dict[str, str] | None:
    """The environment of a Git command against ``root``'s ``origin`` with the run's Bitbucket credential."""
    from ....tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_git_auth_env_async
    from ...named_connections.tool_routing import routed_execute
    from ..platform.dispatch import tool_context
    from ..platform.repo_ref import TOOLS, parse_repository

    ref = parse_repository(run.repository)
    if ref is None or ref.provider != "bitbucket":
        return None
    code, url, _err = await safe_git.git(root, "remote", "get-url", "origin")
    url = url.strip()
    if code != 0 or not url.lower().startswith(("https://", "http://")):
        return None
    async def execute(_params: dict[str, Any], routed: Any) -> dict[str, Any]:
        try:
            return {"env": await _bitbucket_git_auth_env_async(routed, url)}
        except ValueError:
            return {"error": "no_git_credential"}

    try:
        context = await tool_context(db, run, "change", workspace_root=str(root))
        out = await routed_execute(TOOLS["bitbucket"]["prepare"], ref.args(), context, execute)
    except Exception:  # a secret store or route failure: the fetch runs and says why it failed
        logger.warning("Server prepare could not resolve the Git credential: run=%s", run.id)
        return None
    env = out.get("env") if isinstance(out, dict) else None
    if not isinstance(env, dict):
        logger.info("Server prepare fetches without a Git credential: run=%s (no usable Bitbucket connection)", run.id)
        return None
    return env


__all__ = ["origin_git_env"]
