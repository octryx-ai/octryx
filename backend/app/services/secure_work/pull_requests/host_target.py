"""Where a recorded pull request lives and which connection may read it.

A ``WorkPullRequest`` row names its host by its identity (``record_identity``): ``provider``, the host
(``provider_instance``), ``project_key`` / ``repository_slug`` and ``pr_id``. The connection is never invented: it is
the tool router's plan for the repository's binding key (``named_connections.service_config``) in the PR's
Workspace (its Work item's), exactly the connection the governed Bitbucket/GitHub
tools would run on; it must serve the recorded host, and the connection's repository allowlist applies as it does for
those tools.

Every refusal is a :class:`PullRequestHostError` with a closed ``code``:

``provider_unsupported`` · ``repository_unresolved`` · ``pr_id_invalid`` · ``record_out_of_scope`` ·
``connection_refused`` · ``host_mismatch`` ·
``connection_not_configured`` · ``repository_not_allowed`` · ``host_not_found`` ·
``host_permission`` · ``host_unavailable`` · ``host_rejected`` · ``unknown_host_state`` · ``unknown_build_state``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.bitbucket_impl._bitbucket_internal_core import _bitbucket_base_url, _is_repo_allowed

from ....models import WorkPullRequest
from ....tools.bitbucket_impl._bitbucket_cloud import CloudApiError, is_cloud
from ....tools.connectors.github import _github_token, _resolve_github_repo
from ....tools.context import ToolContext
from ...github_url import github_web_base_url
from ...named_connections.service_config import ConnectionRefusalError, service_connection_config
from ...run_capability.worker_profiles import worker_tool_context_state
from .record_identity import in_item_workspace, web_host

# The context's declared class: the refresh only reads the PR.
HOST_READ_PROFILE = "pull_request_host_read"
DEPLOYMENT_SERVER, DEPLOYMENT_CLOUD, DEPLOYMENT_GITHUB = "bitbucket_server", "bitbucket_cloud", "github"
SUPPORTED_PROVIDERS = ("bitbucket", "github")
_PR_NUMBER = re.compile(r"^\d{1,12}$")
BITBUCKET_CLOUD_HOST = "bitbucket.org"
MAX_ERROR_CHARS = 300


class PullRequestHostError(Exception):
    """The host could not be asked or refused; ``code`` is closed, ``message`` bounded and credential-free."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message[:MAX_ERROR_CHARS]
        self.status_code = status_code
        self.details = dict(details or {})


@dataclass(slots=True)
class HostTarget:
    provider: str
    deployment: str
    owner: str
    repo: str
    number: str
    project_id: str
    connection_id: str
    context: ToolContext = field(repr=False)

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"


def error_from_status(status: int, host: str) -> PullRequestHostError:
    if status == 404:
        return PullRequestHostError("host_not_found", f"{host} does not know this pull request (HTTP 404).",
                                    status_code=status)
    if status in (401, 403):
        return PullRequestHostError("host_permission", f"{host} refused the connection's account (HTTP {status}).",
                                    status_code=status)
    if status in (408, 425, 429) or status >= 500:
        return PullRequestHostError("host_unavailable", f"{host} is unavailable (HTTP {status}).", status_code=status)
    return PullRequestHostError("host_rejected", f"{host} rejected the request (HTTP {status}).", status_code=status)


def host_error(error: BaseException, host: str) -> PullRequestHostError:
    """The closed error for an exception of a provider call (never the URL, header or credential)."""
    if isinstance(error, PullRequestHostError):
        return error
    if isinstance(error, CloudApiError):
        if error.status == 0:
            return PullRequestHostError("connection_not_configured", error.message)
        mapped = error_from_status(error.status, host)
        return PullRequestHostError(mapped.code, f"{mapped.message} {error.message}".strip(), status_code=error.status)
    if isinstance(error, httpx.HTTPStatusError):
        return error_from_status(error.response.status_code, host)
    if isinstance(error, httpx.TransportError | TimeoutError | ConnectionError):
        return PullRequestHostError("host_unavailable", f"{host} could not be reached ({type(error).__name__}).")
    if isinstance(error, ValueError):  # a Server path on a Cloud connection (``_server_only``)
        return PullRequestHostError("connection_not_configured", str(error))
    return PullRequestHostError("host_rejected", f"{host} call failed ({type(error).__name__}).")


async def workspace_of(db: AsyncSession, row: WorkPullRequest) -> str:
    """The PR's Workspace: its ``scope_key`` when the record is bound to its Work Item's Workspace
    (``in_item_workspace``); any other record is never read."""
    bound = await db.scalar(select(WorkPullRequest.scope_key).where(WorkPullRequest.id == row.id, in_item_workspace()))
    if not bound:
        raise PullRequestHostError("record_out_of_scope",
                                   "The pull request record is not bound to its Work Item's Workspace.")
    return str(bound)


def connection_host(provider: str, config: dict[str, Any]) -> str:
    """The web host the connection serves: GitHub's web base of its API URL, GitLab's URL, Bitbucket Cloud's, or the
    Bitbucket Server URL's."""
    if provider == "github":
        return web_host(github_web_base_url(config.get("github_url")))
    if provider == "gitlab":
        return web_host(config.get("gitlab_url"))
    return BITBUCKET_CLOUD_HOST if is_cloud(config) else web_host(config.get("bitbucket_url"))


async def resolve_target(db: AsyncSession, row: WorkPullRequest) -> HostTarget:
    provider = str(row.provider or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise PullRequestHostError("provider_unsupported",
                                   f"Pull requests of {provider or '(none)'} are not read from a host.")
    number = str(row.pr_id or "").strip()
    if not _PR_NUMBER.fullmatch(number):
        raise PullRequestHostError("pr_id_invalid", "The recorded pull request id is not a number.")
    owner, repo = str(row.project_key or "").strip(), str(row.repository_slug or "").strip()
    if not owner or not repo:
        raise PullRequestHostError("repository_unresolved",
                                   "The pull request record does not name its repository's owner and slug.")
    project_id = await workspace_of(db, row)
    try:
        served = await service_connection_config(db, project_id, provider, keys=(f"{owner}/{repo}",))
    except ConnectionRefusalError as refused:
        raise PullRequestHostError("connection_refused", f"No connection may serve {owner}/{repo}: {refused}",
                                   details={"router_code": refused.code}) from None
    context = ToolContext(user_id="", project_ids=[project_id], roles=[],
                          session_id="", project_config=dict(served.config), db=db,
                          run_capability=worker_tool_context_state(HOST_READ_PROFILE))
    if provider == "github":
        deployment = DEPLOYMENT_GITHUB
        if not await _github_token(context):
            raise PullRequestHostError("connection_not_configured", "The GitHub connection has no token.")
        if _resolve_github_repo(context, {"repository": f"{owner}/{repo}"}) == (None, None):
            raise PullRequestHostError("repository_not_allowed", f"{owner}/{repo} is not allowed on the connection.")
    else:
        deployment = DEPLOYMENT_CLOUD if is_cloud(served.config) else DEPLOYMENT_SERVER
        if deployment == DEPLOYMENT_SERVER and not _bitbucket_base_url(context):
            raise PullRequestHostError("connection_not_configured", "The Bitbucket connection has no URL.")
        if not _is_repo_allowed(context, owner, repo):
            raise PullRequestHostError("repository_not_allowed", f"{owner}/{repo} is not allowed on the connection.")
    if connection_host(provider, served.config) != row.provider_instance:
        raise PullRequestHostError("host_mismatch", f"The connection serving {owner}/{repo} is not on the recorded "
                                                    f"host {row.provider_instance}.")
    return HostTarget(provider, deployment, owner, repo, number, project_id, served.connection_id, context)


__all__ = ["DEPLOYMENT_CLOUD", "DEPLOYMENT_GITHUB", "DEPLOYMENT_SERVER", "HOST_READ_PROFILE", "HostTarget",
           "PullRequestHostError", "connection_host", "error_from_status", "host_error", "resolve_target",
           "workspace_of"]
