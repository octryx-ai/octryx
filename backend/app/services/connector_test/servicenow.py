"""The ServiceNow connection test: the Table API, or each configured Scripted REST endpoint.

The credential is the connector's (``services/servicenow_auth.py``); a token failure answers its closed code.
With the Table API one ``incident`` record is read. With ``servicenow_api_style=scripted`` the first page
(``sysparm_limit=1``) of every configured endpoint is read and reported per endpoint: ``ok`` with its
``total``, or a closed code (HTTP status, empty answer, unexpected shape). No body, value or token is kept.
"""

from __future__ import annotations

from typing import Any

from app.services.atlassian_auth_modes import AtlassianAuthConfigError

from ..oidc_client_credentials import OidcTokenError
from ..outbound_egress import CONNECTION_SERVICENOW, egress_transport
from ..servicenow_auth import resolve_servicenow_auth, validate_servicenow_auth_config
from ..servicenow_scripted import ScriptedEndpointError, scripted_api
from ..servicenow_scripted_fetch import fetch_records
from .failure import connection_success, http_status_failure


def _token_failure(error: OidcTokenError) -> dict[str, Any]:
    return {"ok": False, "summary": f"ServiceNow: {error}", "auth_code": error.code, "auth_hint": str(error)}


async def test_servicenow_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    base_url = str(config.get("servicenow_url") or "").strip().rstrip("/")
    try:
        validate_servicenow_auth_config(config)
        api = scripted_api(config)
    except (AtlassianAuthConfigError, ScriptedEndpointError) as error:
        return {"ok": False, "summary": str(error)}
    credential = resolve_servicenow_auth(config)
    if not base_url or credential is None:
        return {"ok": False, "summary": "servicenow_url and the credential of the authentication mode are required."}
    headers = {"Accept": "application/json", **credential.headers()}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=False, transport=egress_transport(CONNECTION_SERVICENOW),
        auth=credential.http_auth(),
    ) as client:
        if api is None:
            try:
                response = await client.get(
                    f"{base_url}/api/now/table/incident", params={"sysparm_limit": 1}, headers=headers
                )
            except OidcTokenError as error:
                return _token_failure(error)
            if response.status_code >= 400:
                return http_status_failure("ServiceNow", response.status_code)
            return connection_success("Connected to ServiceNow (Table API).")
        endpoints: dict[str, dict[str, Any]] = {}
        for table, path in api.paths.items():
            try:
                _records, total = await fetch_records(
                    client, base_url, path, table, limit=1, page_size=1, headers=headers
                )
            except OidcTokenError as error:
                return _token_failure(error)
            except ScriptedEndpointError as error:
                endpoints[table] = {"ok": False, "code": error.code, "http_status": error.http_status}
            else:
                endpoints[table] = {"ok": True, "total": total}
    ok = all(endpoint["ok"] for endpoint in endpoints.values())
    summary = "; ".join(
        f"{table}: {'OK, total ' + str(result['total']) if result['ok'] else result['code']}"
        for table, result in endpoints.items()
    )
    return {"ok": ok, "summary": f"ServiceNow Scripted REST: {summary}.", "endpoints": endpoints}


__all__ = ["test_servicenow_connection"]
