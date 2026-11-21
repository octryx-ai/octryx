"""Authentication of the Confluence, Jira and Bitbucket connectors: Atlassian Cloud and Server/Data Center.

Each connector has one non-secret mode field, ``confluence_auth_mode`` / ``jira_auth_mode`` /
``bitbucket_auth_mode``:

``cloud_api_token``
    Basic ``<email>:<API token>``. Confluence: ``confluence_username`` holds the email and
    ``confluence_token`` the token. Jira: ``jira_email`` and ``jira_token``. Bitbucket:
    ``bitbucket_username`` and ``bitbucket_token``.
``basic``
    Basic ``<username>:<password>``. Confluence: ``confluence_username``/``confluence_password``.
    Jira: ``jira_username``/``jira_password``. Bitbucket: ``bitbucket_username``/``bitbucket_password``.
``bearer_pat``
    ``Authorization: Bearer <personal access token>``, from ``confluence_token`` / ``jira_token`` /
    ``bitbucket_token`` (a Bitbucket Data Center HTTP access token). No principal is needed.
``oidc_client_credentials``
    ``Authorization: Bearer <access token>`` of an OpenID Connect client credentials grant at the
    admin-entered ``<product>_oidc_token_url`` with ``<product>_oidc_client_id`` and the secret
    ``<product>_oidc_client_secret`` (optional ``_oidc_scope``, ``_oidc_audience``, ``_oidc_client_auth``).
    No static header exists: the token comes from ``services/oidc_client_credentials.py`` through
    :func:`request_auth`, cached, refreshed and retried once on a 401.

With an explicit mode, only that mode's principal and secret are read. There is never a fallback
to the other secret field, and a Bearer token is never sent as Basic (or the reverse).

Without a mode no credential resolves (the connection needs configuration); a save that stores a principal or
secret without a mode is refused.

Bitbucket Cloud (``bitbucket_deployment: cloud``) has one sign-in, the Atlassian account email and an API
token: its mode is absent or ``cloud_api_token``; any other mode is refused at save. The
Cloud clients read their credential themselves (``tools/bitbucket_impl/_bitbucket_cloud.py``).

A stored mode outside the closed set resolves to no credential, so the request fails closed;
writers refuse it.

Secrets live only in :class:`AtlassianCredential` (excluded from ``repr``) and in the header this
module builds. Messages never contain a secret, a principal or a response body.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from .atlassian_auth_modes import (
    _MODE_FIELDS,
    BITBUCKET,
    JIRA,
    MODE_BEARER_PAT,
    MODE_OIDC_CLIENT_CREDENTIALS,
    SCHEME_BASIC,
    SCHEME_BEARER,
    SCHEME_OIDC,
    _text,
    declared_mode,
)
from .oidc_client_credentials import (
    OidcClientCredentials,
    client_credentials,
    product_fields,
)
from .oidc_token_cache import OidcBearerAuth
from .outbound_egress import CONNECTION_BITBUCKET, CONNECTION_CONFLUENCE, CONNECTION_JIRA


@dataclass(frozen=True, slots=True)
class AtlassianCredential:
    """The resolved credential of one connection and its explicit mode."""

    connector: str
    mode: str
    scheme: str
    principal: str = field(repr=False)
    secret: str = field(repr=False)
    oidc: OidcClientCredentials | None = None

    def headers(self) -> dict[str, str]:
        """The static header; none for ``oidc`` (its token comes through :func:`request_auth`)."""
        if self.scheme == SCHEME_OIDC:
            return {}
        if self.scheme == SCHEME_BEARER:
            return {"Authorization": f"Bearer {self.secret}"}
        token = base64.b64encode(f"{self.principal}:{self.secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}


class _StaticBearerAuth(httpx.Auth):
    """``Authorization: Bearer <token>`` on every request (a personal or HTTP access token)."""

    def __init__(self, token: str) -> None:
        self._token = token

    def __repr__(self) -> str:
        return "_StaticBearerAuth()"

    def auth_flow(self, request: httpx.Request):  # noqa: ANN201 - httpx's generator protocol
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


def credential_auth(
    credential: AtlassianCredential, *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.Auth:
    """The ``httpx`` auth of ``credential``: Basic, a static Bearer, or the client credentials grant's Bearer.

    For a client that cannot add :meth:`AtlassianCredential.headers` per request (one ``auth`` per client).
    The ``oidc`` auth needs an async client; it renews the token and retries once on a 401.
    """
    if credential.oidc is not None:
        return OidcBearerAuth(credential.oidc, transport=transport)
    if credential.scheme == SCHEME_BEARER:
        return _StaticBearerAuth(credential.secret)
    return httpx.BasicAuth(credential.principal, credential.secret)


def resolve_credential(connector: str, config: Mapping[str, Any]) -> AtlassianCredential | None:
    """The credential a request uses, or ``None`` when incomplete or the stored mode is absent or unknown."""
    mode = declared_mode(connector, config)
    fields = _MODE_FIELDS[connector].get(mode) if isinstance(mode, str) else None
    if fields is None:
        return None
    principal_key, secret_key = fields
    secret = _text(config, secret_key)
    if mode == MODE_OIDC_CLIENT_CREDENTIALS:
        connection = (CONNECTION_JIRA if connector == JIRA else CONNECTION_BITBUCKET if connector == BITBUCKET
                      else CONNECTION_CONFLUENCE)
        oidc = client_credentials(config, product_fields(connector), connection=connection)
        if oidc is None:
            return None
        return AtlassianCredential(connector, mode, SCHEME_OIDC, oidc.client_id, oidc.client_secret, oidc)
    if mode == MODE_BEARER_PAT:
        return AtlassianCredential(connector, mode, SCHEME_BEARER, "", secret) if secret else None
    principal = _text(config, principal_key or "")
    if not principal or not secret:
        return None
    return AtlassianCredential(connector, mode, SCHEME_BASIC, principal, secret)


def auth_headers(connector: str, config: Mapping[str, Any]) -> dict[str, str]:
    """The ``Authorization`` header for ``config``; empty when no complete credential resolves."""
    credential = resolve_credential(connector, config)
    return credential.headers() if credential else {}


def request_auth(
    connector: str, config: Mapping[str, Any], *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.Auth | None:
    """The ``httpx`` auth of an ``oidc_client_credentials`` connection, else ``None`` (static headers)."""
    credential = resolve_credential(connector, config)
    if credential is None or credential.oidc is None:
        return None
    return OidcBearerAuth(credential.oidc, transport=transport)


__all__ = [
    "AtlassianCredential",
    "auth_headers",
    "credential_auth",
    "request_auth",
    "resolve_credential",
]
