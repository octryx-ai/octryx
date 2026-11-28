"""Authentication of the Confluence, Jira and Bitbucket connectors: Atlassian Cloud and Server/Data Center. Each
connector has one non-secret mode field, ``<product>_auth_mode``; a missing or unknown mode resolves no credential."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..outbound_egress import CONNECTION_BITBUCKET, CONNECTION_CONFLUENCE, CONNECTION_JIRA
from .atlassian_modes import (
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
from .types import AtlassianAuthMode, AtlassianProduct, AtlassianScheme


@dataclass(frozen=True, slots=True)
class AtlassianCredential:
    connector: AtlassianProduct
    mode: AtlassianAuthMode
    scheme: AtlassianScheme
    principal: str = field(repr=False)
    secret: str = field(repr=False)
    oidc: OidcClientCredentials | None = None

    def headers(self) -> dict[str, str]:
        if self.scheme == SCHEME_OIDC:
            return {}
        if self.scheme == SCHEME_BEARER:
            return {"Authorization": f"Bearer {self.secret}"}
        token = base64.b64encode(f"{self.principal}:{self.secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}


class _StaticBearerAuth(httpx.Auth):
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
    if credential.oidc is not None:
        return OidcBearerAuth(credential.oidc, transport=transport)
    if credential.scheme == SCHEME_BEARER:
        return _StaticBearerAuth(credential.secret)
    return httpx.BasicAuth(credential.principal, credential.secret)


def resolve_credential(connector: str, config: Mapping[str, Any]) -> AtlassianCredential | None:
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
    credential = resolve_credential(connector, config)
    return credential.headers() if credential else {}


def request_auth(
    connector: str, config: Mapping[str, Any], *, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.Auth | None:
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
