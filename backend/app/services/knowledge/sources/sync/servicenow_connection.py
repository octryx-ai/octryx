"""The Workspace's ServiceNow connection, read from its existing ``servicenow`` tool configuration. Secrets are excluded
from ``repr``."""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_SERVICENOW
from ....connector_auth.oidc_client_credentials import OidcTokenError
from ....connector_auth.oidc_token_cache import access_token
from ....connector_auth.servicenow import ServiceNowAuth, resolve_servicenow_auth
from ....connector_auth.servicenow_password_grant import access_token as password_access_token
from ....servicenow_record_limit import RecordLimit, record_limit
from ....servicenow_scripted import ScriptedApi, ScriptedEndpointError, scripted_api
from ...ledger.errors import InvalidEvidenceRequestError
from ..source_url import normalize_source_url
from .contract import REASON_CONNECTION_NOT_CONFIGURED, ConnectorError
from .token_errors import reason_for_token_error


@dataclass(frozen=True, slots=True)
class RequestAuth:
    base_url: str
    header: str = field(repr=False)
    kind: str = CONNECTOR_KIND_SERVICENOW
    credential: ServiceNowAuth | None = field(default=None, repr=False)  # a token grant

    def auth_headers(self) -> dict[str, str]:
        return {**({"Authorization": self.header} if self.header else {}), "Accept": "application/json"}

    def http_auth(self, transport: httpx.AsyncBaseTransport | None = None) -> httpx.Auth | None:
        return self.credential.http_auth(transport) if self.credential is not None else None


@dataclass(frozen=True, slots=True)
class ServiceNowConnection:
    kind: str
    base_url: str
    credential: ServiceNowAuth = field(repr=False)
    # Upper-cased table names of ``servicenow_allowed_tables``; ``None`` when the tool sets none.
    allowed_scopes: frozenset[str] | None = None
    # The Scripted REST endpoints (``servicenow_api_style=scripted``); ``None`` for the Table API.
    api: ScriptedApi | None = None
    # The connector's record limit (groups and services, ``servicenow_record_limit``); ``None``: no limit.
    limit: RecordLimit | None = None

    async def request_auth(self, *, transport: httpx.AsyncBaseTransport | None = None) -> RequestAuth:
        oidc, grant = self.credential.oidc, self.credential.password_grant
        if oidc is None and grant is None:
            return RequestAuth(self.base_url, self.credential.headers()["Authorization"])
        try:  # the run's first grant; the reader reuses the cached token
            if grant is not None:
                await password_access_token(grant, transport=transport)
            else:
                await access_token(oidc, transport=transport)
        except OidcTokenError as error:
            raise ConnectorError(reason_for_token_error(error)) from None
        return RequestAuth(self.base_url, "", credential=self.credential)


def _text(config: dict, key: str) -> str:
    return str(config.get(key) or "").strip()


def _allowed_tables(config: dict) -> frozenset[str] | None:
    raw = config.get("servicenow_allowed_tables")
    items = raw if isinstance(raw, list) else str(raw or "").replace(",", " ").split()
    tables = {str(item).strip().upper() for item in items if str(item).strip()}
    return frozenset(tables) or None


def servicenow_connection(config: dict) -> ServiceNowConnection:
    try:
        base_url = normalize_source_url(_text(config, "servicenow_url").rstrip("/"))
    except InvalidEvidenceRequestError:
        base_url = None
    if base_url is None:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    credential = resolve_servicenow_auth(config)
    if credential is None:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED)
    try:
        api = scripted_api(config)
    except ScriptedEndpointError:
        raise ConnectorError(REASON_CONNECTION_NOT_CONFIGURED) from None
    return ServiceNowConnection(
        kind=CONNECTOR_KIND_SERVICENOW, base_url=base_url, credential=credential,
        allowed_scopes=_allowed_tables(config), api=api, limit=record_limit(config),
    )


__all__ = ["RequestAuth", "ServiceNowConnection", "servicenow_connection"]
