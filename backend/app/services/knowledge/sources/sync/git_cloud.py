"""The connection a ``git_repository`` source without a link reads with (``git_bitbucket.py`` module doc): none for
a public host, the Workspace's Bitbucket Cloud connection for a ``bitbucket.org`` repository."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_GIT_REPOSITORY
from ....atlassian_auth import AtlassianCredential
from ....named_connections.resolver import with_secrets
from ....named_connections.route_planner import plan_route
from ....project.service import get_project_config
from .connections import PublicGitConnection, merged_tool_config
from .contract import REASON_CONNECTION_NOT_CONFIGURED, REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE, ConnectorError
from .git_config import FETCH_REMOTE_GIT, HOST_KIND
from .git_hosts import HOST_BITBUCKET_DATACENTER, parse_repository_url

_PROBE_TOOL = "get_bitbucket_build_statuses"  # a read the Bitbucket connector routes by repository


@dataclass(frozen=True, slots=True)
class ConnectedGitConnection:
    """A repository read with one connection's credential; the credential never appears in a repr.

    ``auth``: Bitbucket Cloud's basic auth for its REST API and archives. ``credential`` and ``base_url``: a Data
    Center connection's sign-in and its URL (Git over HTTPS, ``git_clone.py``)."""

    kind: str = CONNECTOR_KIND_GIT_REPOSITORY
    auth: tuple[str, str] | None = field(default=None, repr=False)
    credential: AtlassianCredential | None = field(default=None, repr=False)
    base_url: str | None = None
    # Data Center: the repository's own Git token, used for Git instead of ``credential``.
    git_token: str | None = field(default=None, repr=False)
    # GitHub: the connection's token, sent as a bearer to ``api.github.com`` only (``git_bitbucket.py`` module doc).
    bearer: str | None = field(default=None, repr=False)


def _listed(config: dict, workspace: str, repo: str) -> bool:
    for entry in config.get("bitbucket_allowed_repos") or []:
        if isinstance(entry, str) and "/" in entry:
            project, slug = entry.split("/", 1)
            enabled = True
        elif isinstance(entry, dict):
            project = str(entry.get("project_key") or entry.get("project") or "")
            slug = str(entry.get("repo_slug") or entry.get("slug") or "")
            enabled = entry.get("enabled", True) is not False
        else:
            continue
        if enabled and project.strip().lower() == workspace and slug.strip().lower() == repo:
            return True
    return False


async def _bitbucket_cloud_config(db: AsyncSession, project_id: str, workspace: str, repo: str) -> dict:
    base = await get_project_config(project_id, db)
    plan = plan_route(_PROBE_TOOL, {"project_key": workspace, "repo_slug": repo}, base)
    if plan.refusal is not None:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
    target = plan.targets[0] if plan.targets else None
    if target is not None:
        return dict((await with_secrets(db, target)).config or {})
    config = await merged_tool_config(db, "bitbucket", project_id)
    if config is None:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    if not _listed(config, workspace, repo):
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED_FOR_SCOPE)
    return config


async def git_repository_connection(
    db: AsyncSession, project_id: str, scope: dict | None
) -> PublicGitConnection | ConnectedGitConnection:
    remote = (scope or {}).get("remote")
    if not remote or (scope or {}).get("fetch_mode") != FETCH_REMOTE_GIT:
        # A local snapshot fetches nothing (its run is refused as snapshot_upload_required): no connection, any host.
        return PublicGitConnection()
    if (scope or {}).get(HOST_KIND) == HOST_BITBUCKET_DATACENTER:
        # A Data Center repository is read only through its linked connection; the link is gone.
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    location = parse_repository_url(remote, known_host_only=True)
    if location.host is None or not location.host.credential_connector:
        return PublicGitConnection()
    workspace, repo = (part.lower() for part in location.path.split("/", 1))
    config = await _bitbucket_cloud_config(db, project_id, workspace, repo)
    email = str(config.get("bitbucket_username") or "").strip()
    token = str(config.get("bitbucket_token") or "").strip()
    if str(config.get("bitbucket_deployment") or "").strip().lower() != "cloud" or not email or not token:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    return ConnectedGitConnection(auth=(email, token))
