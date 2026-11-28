"""What a connection's account can actually see: the "list visible scopes" probes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.connector_auth.atlassian_modes import CONFLUENCE, JIRA

from ..connector_auth.atlassian import request_auth, resolve_credential
from ..connector_auth.oidc_client_credentials import OidcTokenError
from ..connector_auth.servicenow import resolve_servicenow_auth
from ..outbound_egress import CONNECTION_CONFLUENCE, CONNECTION_JIRA, CONNECTION_SERVICENOW, egress_transport
from ..servicenow_scripted import ScriptedEndpointError, scripted_api

PAGE_SIZE = 100
MAX_PAGES = 5
MAX_VISIBLE = PAGE_SIZE * MAX_PAGES
MAX_DIRECT = 20
TIMEOUT_SECONDS = 15
CODE_UNAVAILABLE = "visible_scopes_unavailable"

_CONFLUENCE_KEY = re.compile(r"^~?[A-Za-z0-9_]{1,64}$")
_JIRA_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_TABLE = re.compile(r"^[A-Za-z0-9_]{1,80}$")


@dataclass(frozen=True, slots=True)
class VisibleScopes:
    keys: tuple[str, ...] = ()
    complete: bool = True
    # Configured keys checked one by one (beyond a cut listing): key -> visible.
    direct: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    http_status: int | None = None


class _ProbeFailedError(Exception):
    def __init__(self, code: str, http_status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.http_status = http_status


def _keys(values: Iterable[Any], pattern: re.Pattern[str]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and pattern.fullmatch(value.strip())]


async def _get(client: Any, url: str, headers: dict[str, str], params: dict[str, Any] | None = None) -> Any:
    try:
        response = await client.get(url, headers=headers, params=params)
    except OidcTokenError as error:
        raise _ProbeFailedError(error.code) from None
    return response


async def _direct(client: Any, url_of, headers: dict[str, str], keys: Iterable[str]) -> dict[str, bool]:
    found: dict[str, bool] = {}
    for key in list(keys)[:MAX_DIRECT]:
        response = await _get(client, url_of(key), headers)
        if response.status_code in (401, 403, 404):
            found[key] = False
        elif response.status_code >= 400:
            raise _ProbeFailedError(CODE_UNAVAILABLE, response.status_code)
        else:
            found[key] = True
    return found


def _missing_from(listed: Iterable[str], configured: frozenset[str] | None) -> list[str]:
    seen = {key.upper() for key in listed}
    return sorted(key for key in configured or () if key.upper() not in seen)


async def _run(probe, *args) -> VisibleScopes:
    try:
        return await probe(*args)
    except _ProbeFailedError as failed:
        return VisibleScopes(complete=False, error=failed.code, http_status=failed.http_status)
    except (httpx.HTTPError, ValueError):
        # Transport errors (timeout, refused, TLS) and an answer that is not JSON: unavailable, no detail kept.
        return VisibleScopes(complete=False, error=CODE_UNAVAILABLE)


async def confluence_spaces(config: dict, configured: frozenset[str] | None, *, httpx_module: Any) -> VisibleScopes:
    async def probe() -> VisibleScopes:
        base = str(config.get("confluence_url") or "").strip().rstrip("/")
        credential = resolve_credential(CONFLUENCE, config)
        headers = {"Accept": "application/json", **(credential.headers() if credential else {})}
        listed: list[str] = []
        complete = False
        async with httpx_module.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, transport=egress_transport(CONNECTION_CONFLUENCE),
            auth=request_auth(CONFLUENCE, config),
        ) as client:
            for page in range(MAX_PAGES):
                response = await _get(client, f"{base}/rest/api/space", headers,
                                      {"start": page * PAGE_SIZE, "limit": PAGE_SIZE})
                if response.status_code >= 400:
                    raise _ProbeFailedError(CODE_UNAVAILABLE, response.status_code)
                payload = response.json()
                results = payload.get("results") if isinstance(payload, dict) else None
                if not isinstance(results, list):
                    raise _ProbeFailedError(CODE_UNAVAILABLE)
                listed += _keys((item.get("key") for item in results if isinstance(item, dict)), _CONFLUENCE_KEY)
                if len(results) < PAGE_SIZE or not (payload.get("_links") or {}).get("next"):
                    complete = True
                    break
            direct = {} if complete else await _direct(
                client, lambda key: f"{base}/rest/api/space/{key}", headers, _missing_from(listed, configured))
        return VisibleScopes(tuple(listed), complete, direct)

    return await _run(probe)


async def jira_projects(config: dict, configured: frozenset[str] | None, *, httpx_module: Any) -> VisibleScopes:
    async def probe() -> VisibleScopes:
        base = str(config.get("jira_url") or "").strip().rstrip("/")
        credential = resolve_credential(JIRA, config)
        headers = {"Accept": "application/json", **(credential.headers() if credential else {})}
        async with httpx_module.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True, transport=egress_transport(CONNECTION_JIRA),
            auth=request_auth(JIRA, config),
        ) as client:
            response = await _get(client, f"{base}/rest/api/2/project", headers)
            if response.status_code >= 400:
                raise _ProbeFailedError(CODE_UNAVAILABLE, response.status_code)
            payload = response.json()
            if not isinstance(payload, list):
                raise _ProbeFailedError(CODE_UNAVAILABLE)
            listed = _keys((item.get("key") for item in payload if isinstance(item, dict)), _JIRA_KEY)
            complete = len(listed) <= MAX_VISIBLE
            listed = listed[:MAX_VISIBLE]
            direct = {} if complete else await _direct(
                client, lambda key: f"{base}/rest/api/2/project/{key}", headers, _missing_from(listed, configured))
        return VisibleScopes(tuple(listed), complete, direct)

    return await _run(probe)


async def servicenow_tables(
    config: dict, configured: frozenset[str] | None, *, httpx_module: Any
) -> VisibleScopes | None:
    try:
        if scripted_api(config) is not None:
            return None  # Scripted REST: the connection test reports each endpoint already
    except ScriptedEndpointError:
        return None
    tables = sorted(key for key in configured or () if _TABLE.fullmatch(key))
    if not tables:
        return None  # no configured table: nothing to compare, and no cheap listing of tables exists

    async def probe() -> VisibleScopes:
        base = str(config.get("servicenow_url") or "").strip().rstrip("/")
        credential = resolve_servicenow_auth(config)
        headers = {"Accept": "application/json", **(credential.headers() if credential else {})}
        async with httpx_module.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=egress_transport(CONNECTION_SERVICENOW),
            auth=credential.http_auth() if credential else None,
        ) as client:
            direct = await _direct(
                client, lambda table: f"{base}/api/now/table/{table}?sysparm_limit=1", headers, tables)
        return VisibleScopes(tuple(key for key, seen in direct.items() if seen), True, direct)

    return await _run(probe)


__all__ = [
    "CODE_UNAVAILABLE",
    "MAX_DIRECT",
    "MAX_VISIBLE",
    "VisibleScopes",
    "confluence_spaces",
    "jira_projects",
    "servicenow_tables",
]
