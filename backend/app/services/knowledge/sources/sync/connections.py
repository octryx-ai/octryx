"""The Workspace's Confluence, Jira or ServiceNow connection, read from its existing tool configuration.

No credential is stored by Source Sync. The connection is the Workspace's built-in tool config for
``confluence`` or ``jira`` (``BuiltInToolConfig``), exactly as the Confluence and Jira tools use
it: the active project entry, over the global entry, with ``*_secret_ref`` fields resolved through
the secret store (``services/secret``). The credential is one unit per connection: a Workspace
entry that sets any credential or URL field inherits no global credential field
(``tool_config/connection_fields.py``). Only that one tool's config is resolved, never every tool's.
A Workspace without an active entry, a URL or a credential is ``connection_not_configured``; when the
Workspace entry sets its own connection but that unit lacks its URL or credential, the run says so:
``own_connection_incomplete``.
ServiceNow reads the same resolved entry through ``servicenow_connection.py`` (bearer, OAuth or Basic).
A ``git_repository`` reads public repositories without any credential: its connection is the
credential-free :class:`PublicGitConnection`, and no tool configuration is read for it. A kind registered with a
resolver of its own (``kinds.py``; ``custom_rest`` resolves its REST definition) is resolved by it.

The resolved secret lives only in this frozen value, is excluded from ``repr``, and is turned into
an ``Authorization`` header at the transport; it is never logged, returned or persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.atlassian_auth_modes import SCHEME_BASIC
from app.services.atlassian_auth_validation import confluence_cloud_url_problem
from app.services.named_connections.workspace_routes import workspace_routes

from .....models.project.knowledge_source_sync import (
    CONNECTOR_KIND_CONFLUENCE,
    CONNECTOR_KIND_GIT_REPOSITORY,
    CONNECTOR_KIND_JIRA,
    CONNECTOR_KIND_KUBERNETES,
    CONNECTOR_KIND_SERVICENOW,
)
from ....atlassian_auth import AtlassianCredential, resolve_credential
from ....confluence_pages.rules import PAGES_FIELD, PageRule, normalize_page_rules
from ....named_connections.unbound_default import apply_default
from ....oidc_client_credentials import OidcClientCredentials
from ....oidc_token_cache import OidcBearerAuth
from ....secret import resolve_secret_refs
from ....tool_config import get_tool_config
from ....tool_config.connection_fields import global_config_for_scope, sets_connection_identity
from ...ledger.errors import InvalidEvidenceRequestError
from ..source_url import normalize_source_url
from .contract import (
    REASON_CONFLUENCE_CLOUD_URL_WITHOUT_WIKI,
    REASON_CONNECTION_NOT_CONFIGURED,
    REASON_OWN_CONNECTION_INCOMPLETE,
    ConnectorError,
)
from .kubernetes_connection import KubernetesConnection, kubernetes_connection
from .servicenow_connection import ServiceNowConnection, servicenow_connection

# The URL key per connector kind; the credential follows the connector's auth mode
# (``services/atlassian_auth.py``), exactly as the Confluence and Jira tools resolve it.
_URL_KEYS = {CONNECTOR_KIND_CONFLUENCE: "confluence_url", CONNECTOR_KIND_JIRA: "jira_url"}


@dataclass(frozen=True, slots=True)
class SourceConnection:
    """Base URL and credential of one source system, plus the tool's own scope allowlist.

    ``scheme`` is ``basic`` (principal and secret), ``bearer`` (a personal access token, no
    principal) or ``oidc`` (a client credentials grant, ``oidc`` set), as the connector's auth
    mode resolves it.

    ``allowed_scopes`` is ``None`` when the tool config places no restriction (Jira without
    ``jira_allowed_projects``), else the enabled space or project keys, upper-cased.

    ``page_rules`` (Confluence): the connection's page allowlist (``confluence_allowed_pages``), which narrows
    the listed pages exactly as it narrows the Confluence tools (``services/confluence_pages/rules.py``).
    """

    kind: str
    base_url: str
    principal: str = field(repr=False)
    secret: str = field(repr=False)
    allowed_scopes: frozenset[str] | None = None
    scheme: str = SCHEME_BASIC
    oidc: OidcClientCredentials | None = None
    page_rules: tuple[PageRule, ...] = ()

    def auth_headers(self) -> dict[str, str]:
        credential = AtlassianCredential(self.kind, None, self.scheme, self.principal, self.secret)
        return {**credential.headers(), "Accept": "application/json"}

    def http_auth(self, transport: httpx.AsyncBaseTransport | None = None) -> httpx.Auth | None:
        """The token auth of a client credentials connection (cached, retried once on a 401), else none."""
        return OidcBearerAuth(self.oidc, transport=transport) if self.oidc is not None else None


@dataclass(frozen=True, slots=True)
class PublicGitConnection:
    """The connection of a public ``git_repository``: nothing to resolve and no credential."""

    kind: str = CONNECTOR_KIND_GIT_REPOSITORY


def _allowed_scopes(kind: str, config: dict) -> frozenset[str] | None:
    if kind == CONNECTOR_KIND_CONFLUENCE:
        # The Confluence tools read nothing outside the enabled spaces; an empty list allows nothing.
        keys: set[str] = set()
        for entry in config.get("confluence_allowed_spaces") or []:
            if isinstance(entry, str):
                keys.add(entry.strip().upper())
            elif isinstance(entry, dict) and entry.get("enabled", True):
                keys.add(str(entry.get("space_key") or entry.get("key") or "").strip().upper())
        default_space = str(config.get("confluence_space_key") or "").strip().upper()
        if not keys and default_space:
            keys.add(default_space)
        return frozenset(key for key in keys if key)
    raw = config.get("jira_allowed_projects")
    if raw is None:
        return None
    items = raw if isinstance(raw, list) else str(raw).replace(",", " ").split()
    keys = {str(item).strip().upper() for item in items if str(item).strip()}
    return frozenset(keys) or None


async def merged_tool_config(db: AsyncSession, kind: str, project_id: str) -> dict | None:
    project_entry = await get_tool_config(db, kind, project_id)
    if project_entry is None or not project_entry.is_active:
        return None
    merged: dict = {}
    global_entry = await get_tool_config(db, kind, None)
    if global_entry is not None and global_entry.is_active and global_entry.config:
        global_config = await resolve_secret_refs(db, global_entry.config, tool_name=kind, project_id=None)
        # The credential unit is never mixed across scopes (connection_fields.py).
        merged.update(global_config_for_scope(kind, global_config, project_entry.config))
    if project_entry.config:
        merged.update(await resolve_secret_refs(db, project_entry.config, tool_name=kind, project_id=project_id))
    # The default connection (the one available connection that binds no key) replaces the entry's unit.
    default = (await workspace_routes(db, project_id, (kind,), secrets=False)).default_of(kind)
    return await apply_default(db, merged, default) if default is not None else merged


async def _unusable_reason(db: AsyncSession, kind: str, project_id: str) -> str:
    """Why a resolved connection has no URL or credential: an incomplete own unit, or nothing configured."""
    entry = await get_tool_config(db, kind, project_id)
    own = entry is not None and sets_connection_identity(kind, entry.config)
    return REASON_OWN_CONNECTION_INCOMPLETE if own else REASON_CONNECTION_NOT_CONFIGURED


async def resolve_connection(
    db: AsyncSession, *, kind: str, project_id: str, scope: dict | None = None
) -> SourceConnection | ServiceNowConnection | PublicGitConnection | KubernetesConnection:
    """The Workspace's active connection for ``kind``, or ``connection_not_configured``.

    A ``git_repository`` is public (no connection) unless its host is read through one (``git_bitbucket.py``)."""
    if kind == CONNECTOR_KIND_GIT_REPOSITORY:
        from app.services.knowledge.sources.sync.git_cloud import git_repository_connection

        return await git_repository_connection(db, project_id, scope)
    from .kinds import KINDS  # the registry imports the connectors, which import this module

    own = KINDS[kind].resolve if kind in KINDS else None
    if own is not None:
        # A kind with a connection of its own (``custom_rest``: its REST definition), never a tool configuration.
        return await own(db, project_id, dict(scope or {}))
    if kind not in (CONNECTOR_KIND_SERVICENOW, CONNECTOR_KIND_KUBERNETES, *_URL_KEYS):
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    config = await merged_tool_config(db, kind, project_id)
    if config is None:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    if kind == CONNECTOR_KIND_SERVICENOW:
        return servicenow_connection(config)
    connection = connection_from_config(kind, config)
    if connection is None:
        raise ConnectorError(await _unusable_reason(db, kind, project_id))
    return connection


def connection_from_config(
    kind: str, config: dict
) -> SourceConnection | ServiceNowConnection | KubernetesConnection | None:
    """The connection one resolved config describes; ``None`` without a usable URL or credential.

    Shared by the default entry and the named connections, so both follow the same rules.
    A Kubernetes connection is the API path only (URL and token), never a kubeconfig or the pod's
    own service account.
    """
    if kind == CONNECTOR_KIND_KUBERNETES:
        return kubernetes_connection(config)
    if kind == CONNECTOR_KIND_SERVICENOW:
        try:
            return servicenow_connection(config)
        except ConnectorError as error:
            if error.reason == REASON_CONNECTION_NOT_CONFIGURED:
                return None
            raise
    url_key = _URL_KEYS[kind]
    credential = resolve_credential(kind, config)
    try:
        base_url = normalize_source_url(str(config.get(url_key) or "").strip().rstrip("/"))
    except InvalidEvidenceRequestError:
        base_url = None
    if base_url is None or credential is None:
        return None
    if kind == CONNECTOR_KIND_CONFLUENCE and confluence_cloud_url_problem(base_url):
        # Refused at configure and run alike, never rewritten (same rule as the connection test).
        raise ConnectorError(REASON_CONFLUENCE_CLOUD_URL_WITHOUT_WIKI)
    return SourceConnection(
        kind=kind,
        base_url=base_url,
        principal=credential.principal,
        secret=credential.secret,
        allowed_scopes=_allowed_scopes(kind, config),
        scheme=credential.scheme,
        oidc=credential.oidc,
        page_rules=normalize_page_rules(config.get(PAGES_FIELD)) if kind == CONNECTOR_KIND_CONFLUENCE else (),
    )


__all__ = [
    "PublicGitConnection",
    "SourceConnection",
    "connection_from_config",
    "merged_tool_config",
    "resolve_connection",
]
