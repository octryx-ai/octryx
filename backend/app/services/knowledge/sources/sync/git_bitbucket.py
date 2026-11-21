"""The connection a ``git_repository`` connector reads with: none for a public host, the Workspace's Bitbucket Cloud
connection for a ``bitbucket.org`` repository.

A Bitbucket Cloud repository ``<workspace>/<repo>`` is read with exactly the connection the Bitbucket tools would
use for it (the same route plan over the Workspace's merged config): the named connection that binds it, else the
Workspace's own default entry when its allowlist names it. That connection must be a Bitbucket Cloud connection
(``bitbucket_deployment: cloud``) with the account email and its API token; the reader then gets that basic auth
only. Anything else refuses the run with a fixed reason (``connection_not_configured_for_scope`` or
``connection_not_configured``) — another account is never tried and no URL or credential is ever reported.

A source **linked** to a Bitbucket connection (``knowledge_source_connectors.connection_id``) reads with exactly that
connection (:func:`linked_git_connection`), after the link's grant in the Workspace (``linked_connection.py``) and
the ``knowledge`` deviation's scope (the repository ``KEY/slug``):

- a Data Center connection (``bitbucket_deployment`` ``datacenter`` or none): the source's repository must be on the
  connection's own URL (``host_base`` saved with the source equals the connection's ``bitbucket_url`` now), and Git
  gets the connection's sign-in (``atlassian_auth``: Basic, a personal access token, or the OpenID Connect client
  credentials grant's token; ``git_clone.py``), or the repository's own Git token when the Workspace set one
  (``repository_git_token.py``: Data Center answers 500 on ``/scm/`` for the OpenID Connect token);
- a Cloud connection: a ``bitbucket.org`` repository, read with the account email and its API token.

A source linked to a **GitHub** connection with a token (a private ``github.com`` repository read
anonymously answers ``404``, ``source_not_found``) reads with that token, sent to ``api.github.com`` only
(``git_http.py``); the repository must be on ``github.com`` and the connection must not name another GitHub API
(Enterprise Server), else ``connection_pin_mismatch``, and inside the ``knowledge`` deviation's scope like Bitbucket
(an ``owner`` entry covers every ``owner/<repo>``, ``owner/repo`` exactly that one; else ``scope_not_allowed``). A
GitHub connection without a token (``auth: none``) keeps reading anonymously.

Anything else is refused with a fixed reason (``connection_pin_mismatch``, ``own_connection_incomplete``).
"""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.atlassian_auth_modes import BITBUCKET, is_bitbucket_cloud

from .....models import ConnectorNamedConnection
from ....atlassian_auth import resolve_credential
from ....github_url import normalize_github_api_base_url
from ....named_connections.descriptor import UnitIncompleteError
from ....named_connections.descriptors import descriptor_of
from ....named_connections.grants import grant_for
from ....named_connections.linked_use import USE_KNOWLEDGE, deviation_refusal
from ....named_connections.store import resolved_config, to_value
from ...ledger.errors import InvalidEvidenceRequestError
from ..repository_git_token import source_repository, usable_git_token
from .contract import (
    REASON_CONNECTION_DISABLED,
    REASON_CONNECTION_NOT_AVAILABLE,
    REASON_CONNECTION_PIN_MISMATCH,
    REASON_CONNECTION_PIN_UNKNOWN,
    REASON_OWN_CONNECTION_INCOMPLETE,
    REASON_REPOSITORY_NOT_ON_CONNECTION_HOST,
    ConnectorError,
)
from .git_cloud import ConnectedGitConnection
from .git_config import (
    ACCESS_MODE,
    ACCESS_READ_ONLY,
    HOST_BASE,
    HOST_KIND,
    repository_location,
    validate_git_scope,
)
from .git_hosts import GITHUB as GITHUB_HOST
from .git_hosts import HOST_BITBUCKET_DATACENTER, datacenter_base, parse_repository_url

GITHUB_CONNECTOR = "github"


async def bitbucket_connection_config(db: AsyncSession, row: ConnectorNamedConnection) -> dict:
    """The connection's own fields with its secrets resolved; an incomplete unit is ``own_connection_incomplete``."""
    config = await resolved_config(db, to_value(row))
    descriptor = descriptor_of(BITBUCKET)
    try:
        if descriptor is not None and descriptor.runtime_guard is not None:
            descriptor.runtime_guard(config)
    except UnitIncompleteError:
        raise ConnectorError(REASON_OWN_CONNECTION_INCOMPLETE) from None
    return config


def connected_from_config(config: dict) -> ConnectedGitConnection:
    """The Git reader's connection of a Bitbucket connection's resolved ``config`` (Cloud or Data Center)."""
    if is_bitbucket_cloud(config):
        email = str(config.get("bitbucket_username") or "").strip()
        token = str(config.get("bitbucket_token") or "").strip()
        if not email or not token:
            raise ConnectorError(REASON_OWN_CONNECTION_INCOMPLETE)
        return ConnectedGitConnection(auth=(email, token))
    base = datacenter_base(config.get("bitbucket_url"))
    credential = resolve_credential(BITBUCKET, config)
    if base is None or credential is None:
        raise ConnectorError(REASON_OWN_CONNECTION_INCOMPLETE)
    return ConnectedGitConnection(credential=credential, base_url=base)


def repository_key(scope: dict) -> str | None:
    """``KEY/slug`` (Data Center) or ``workspace/slug`` (Cloud) of a stored remote, else ``None``."""
    remote = scope.get("remote")
    try:
        if scope.get(HOST_KIND) == HOST_BITBUCKET_DATACENTER:
            return repository_location(remote, datacenter_base=str(scope.get(HOST_BASE) or "")).path
        location = parse_repository_url(remote, known_host_only=True)
    except InvalidEvidenceRequestError:
        return None
    return location.path if location.host is not None and location.host.credential_connector else None


async def linked_git_connection(
    db: AsyncSession, project_id: str, scope: dict, connection_id: str
) -> ConnectedGitConnection | None:
    """The linked Bitbucket or GitHub connection of a ``git_repository`` source (module doc); ``None`` for another
    type or a GitHub connection without a token (anonymous)."""
    row = await db.get(ConnectorNamedConnection, connection_id)
    if row is None:
        raise ConnectorError(REASON_CONNECTION_PIN_UNKNOWN)
    if row.tool_name == GITHUB_CONNECTOR:
        return await _github_connection(db, project_id, scope, row)
    if row.tool_name != BITBUCKET:
        return None
    key = repository_key(scope)
    if key is None:
        raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH)
    refused = deviation_refusal(await grant_for(db, row, project_id), USE_KNOWLEDGE, BITBUCKET, (key,))
    if refused is not None:
        raise ConnectorError(refused.code)
    connection = connected_from_config(await bitbucket_connection_config(db, row))
    datacenter = scope.get(HOST_KIND) == HOST_BITBUCKET_DATACENTER
    if (connection.base_url is not None) != datacenter or (
        datacenter and scope.get(HOST_BASE) != connection.base_url
    ):
        # The source's repository is not on this connection's host (any more): its credential is never sent there.
        raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH)
    if datacenter:
        # Git over HTTPS with the repository's own token when the Workspace set one (``repository_git_token.py``).
        token = await usable_git_token(db, project_id, source_repository(scope))
        if token:
            return replace(connection, git_token=token)
    return connection


async def _github_connection(
    db: AsyncSession, project_id: str, scope: dict, row: ConnectorNamedConnection
) -> ConnectedGitConnection | None:
    config = await resolved_config(db, to_value(row))
    token = str(config.get("github_token") or "").strip()
    if not token:
        return None  # a public connection (``auth: none``) reads anonymously
    try:
        location = parse_repository_url(scope.get("remote"), known_host_only=True)
    except InvalidEvidenceRequestError:
        location = None
    if location is None or location.host is not GITHUB_HOST:
        raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH)
    if normalize_github_api_base_url(config.get("github_url")) != GITHUB_HOST.api_base:
        raise ConnectorError(REASON_CONNECTION_PIN_MISMATCH)  # the token belongs to another GitHub
    # The link's grant and its ``knowledge`` use were checked before (``linked_connection.check_linked_grant``); the
    # token reads only a repository inside the use's scope (an ``owner`` entry covers its repositories).
    refused = deviation_refusal(await grant_for(db, row, project_id), USE_KNOWLEDGE, GITHUB_CONNECTOR,
                                (location.path,))
    if refused is not None:
        raise ConnectorError(refused.code)
    return ConnectedGitConnection(bearer=token)


async def usable_connection(db: AsyncSession, project_id: str, connection_id: str) -> ConnectorNamedConnection:
    """The connection row, if available and active in the Workspace with its ``knowledge`` use on; else the refusal."""
    row = await db.get(ConnectorNamedConnection, connection_id)
    if row is None:
        raise ConnectorError(REASON_CONNECTION_PIN_UNKNOWN)
    grant = await grant_for(db, row, project_id)
    if grant is None:
        raise ConnectorError(REASON_CONNECTION_NOT_AVAILABLE)
    if not grant.is_active:
        raise ConnectorError(REASON_CONNECTION_DISABLED)
    refused = deviation_refusal(grant, USE_KNOWLEDGE, str(row.tool_name), ())
    if refused is not None:
        raise ConnectorError(refused.code)
    return row


async def bind_repository_scope(
    db: AsyncSession, project_id: str, connection_id: str, fields: dict, stored_scope: dict | None
) -> dict:
    """The scope of a ``git_repository`` source saved with ``connection_id`` (the configure path).

    The connection must be usable here; the repository must be on its host (a Data Center connection's URL, or
    ``bitbucket.org`` for Cloud; a GitHub connection reads ``github.com`` anonymously), else
    ``repository_not_on_connection_host``. A Bitbucket source keeps its ``access_mode`` (default ``read_only``)."""
    row = await usable_connection(db, project_id, connection_id)
    fields = dict(fields)
    access_mode = fields.pop("access_mode", None)
    if row.tool_name == GITHUB_CONNECTOR:
        location = _location_or_refused(fields.get("repository_url"), None)
        if location.host is None or location.host.name != "github.com":
            raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST)
        return validate_git_scope(**fields)
    if row.tool_name != BITBUCKET:
        raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST)
    connection = connected_from_config(await bitbucket_connection_config(db, row))
    location = _location_or_refused(fields.get("repository_url"), connection.base_url)
    if connection.base_url is None and (location.host is None or location.host.credential_connector != BITBUCKET):
        raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST)
    refused = deviation_refusal(await grant_for(db, row, project_id), USE_KNOWLEDGE, BITBUCKET, (location.path,))
    if refused is not None:
        raise ConnectorError(refused.code)
    if access_mode is None:
        access_mode = (stored_scope or {}).get(ACCESS_MODE) or ACCESS_READ_ONLY
    return validate_git_scope(**fields, datacenter_base=connection.base_url, access_mode=access_mode)


def _location_or_refused(url: object, base: str | None):
    try:
        return repository_location(url, datacenter_base=base)
    except InvalidEvidenceRequestError:
        raise ConnectorError(REASON_REPOSITORY_NOT_ON_CONNECTION_HOST) from None


__all__ = [
    "bind_repository_scope",
    "usable_connection",
    "bitbucket_connection_config",
    "connected_from_config",
    "linked_git_connection",
    "repository_key",
]
