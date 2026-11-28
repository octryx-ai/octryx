"""The connection a ``git_repository`` connector reads with: none for a public host, else the Bitbucket connection that
binds it."""

from __future__ import annotations

from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import BITBUCKET, is_bitbucket_cloud

from .....models import ConnectorNamedConnection
from ....connector_auth.atlassian import resolve_credential
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
    config = await resolved_config(db, to_value(row))
    descriptor = descriptor_of(BITBUCKET)
    try:
        if descriptor is not None and descriptor.runtime_guard is not None:
            descriptor.runtime_guard(config)
    except UnitIncompleteError:
        raise ConnectorError(REASON_OWN_CONNECTION_INCOMPLETE) from None
    return config


def connected_from_config(config: dict) -> ConnectedGitConnection:
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
