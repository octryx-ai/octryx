from __future__ import annotations

from typing import Any

from app.services.outbound_egress import (
    CONNECTION_DATADOG,
    CONNECTION_MICROSOFT_GRAPH,
    CONNECTION_NEWRELIC,
    CONNECTION_SNYK,
    CONNECTION_SONARQUBE,
    CONNECTION_SPLUNK,
    CONNECTION_VAULT,
    egress_transport,
)

from .failure import connection_success, http_status_failure


async def test_outlook_calendar_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    graph_url = str(config.get("outlook_graph_url") or "https://graph.microsoft.com/v1.0").strip().rstrip("/")
    mailbox = str(config.get("outlook_default_mailbox") or "").strip()
    access_token = str(config.get("outlook_access_token") or "").strip()
    tenant_id = str(config.get("outlook_tenant_id") or "").strip()
    client_id = str(config.get("outlook_client_id") or "").strip()
    client_secret = str(config.get("outlook_client_secret") or "").strip()
    if not mailbox:
        return {"ok": False, "summary": "outlook_default_mailbox is required."}
    token = access_token
    if not token:
        if not tenant_id or not client_id or not client_secret:
            return {
                "ok": False,
                "summary": "Either outlook_access_token or tenant/client credentials are required.",
            }
        async with httpx_module.AsyncClient(
            timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_MICROSOFT_GRAPH)
        ) as client:
            token_response = await client.post(
                f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if token_response.status_code >= 400:
            return http_status_failure("Outlook token exchange", token_response.status_code)
        token = str((token_response.json() or {}).get("access_token") or "").strip()
        if not token:
            return {"ok": False, "summary": "Outlook token exchange did not return an access token."}

    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_MICROSOFT_GRAPH)
    ) as client:
        response = await client.get(
            f"{graph_url}/users/{mailbox}/events",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"$top": 1},
        )
    if response.status_code >= 400:
        return http_status_failure("Outlook calendar endpoint", response.status_code)
    payload = response.json()
    sample_events = len(payload.get("value") or [])
    return connection_success("Connected to Outlook calendar.", counts={"sample_events": sample_events})


async def test_vault_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    vault_url = str(config.get("vault_url") or "").strip().rstrip("/")
    vault_token = str(config.get("vault_token") or "").strip()
    if not vault_url or not vault_token:
        return {"ok": False, "summary": "vault_url and vault_token are required."}
    headers = {"X-Vault-Token": vault_token, "Accept": "application/json"}
    namespace = str(config.get("vault_namespace") or "").strip()
    if namespace:
        headers["X-Vault-Namespace"] = namespace
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_VAULT)
    ) as client:
        response = await client.get(
            f"{vault_url}/v1/auth/token/lookup-self",
            headers=headers,
        )
    if response.status_code >= 400:
        return http_status_failure("Vault", response.status_code)
    return connection_success("Connected to Vault.")


async def test_sonarqube_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    sonarqube_url = str(config.get("sonarqube_url") or "").strip().rstrip("/")
    sonarqube_token = str(config.get("sonarqube_token") or "").strip()
    if not sonarqube_url or not sonarqube_token:
        return {"ok": False, "summary": "sonarqube_url and sonarqube_token are required."}
    auth = httpx_module.BasicAuth(sonarqube_token, "")
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_SONARQUBE)
    ) as client:
        response = await client.get(
            f"{sonarqube_url}/api/system/status",
            auth=auth,
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("SonarQube", response.status_code)
    payload = response.json()
    return connection_success("Connected to SonarQube.", version=payload.get("version"))


async def test_snyk_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    snyk_url = str(config.get("snyk_url") or "https://api.snyk.io").strip().rstrip("/")
    snyk_token = str(config.get("snyk_token") or "").strip()
    org_id = str(config.get("snyk_org_id") or "").strip()
    if not snyk_url or not snyk_token or not org_id:
        return {"ok": False, "summary": "snyk_url, snyk_token and snyk_org_id are required."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_SNYK)
    ) as client:
        response = await client.get(
            f"{snyk_url}/v1/org/{org_id}",
            headers={"Authorization": f"token {snyk_token}", "Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("Snyk", response.status_code)
    return connection_success("Connected to Snyk.")


async def test_datadog_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    datadog_url = str(config.get("datadog_url") or "https://api.datadoghq.com").strip().rstrip("/")
    api_key = str(config.get("datadog_api_key") or "").strip()
    app_key = str(config.get("datadog_app_key") or "").strip()
    if not datadog_url or not api_key or not app_key:
        return {"ok": False, "summary": "datadog_url, datadog_api_key and datadog_app_key are required."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_DATADOG)
    ) as client:
        response = await client.get(
            f"{datadog_url}/api/v1/validate",
            headers={
                "DD-API-KEY": api_key,
                "DD-APPLICATION-KEY": app_key,
                "Accept": "application/json",
            },
        )
    if response.status_code >= 400:
        return http_status_failure("Datadog", response.status_code)
    payload = response.json()
    if payload.get("valid") is not True:
        return {"ok": False, "summary": "Datadog credentials were rejected."}
    return connection_success("Connected to Datadog.")


async def test_newrelic_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    newrelic_url = str(config.get("newrelic_url") or "https://api.newrelic.com").strip().rstrip("/")
    api_key = str(config.get("newrelic_api_key") or "").strip()
    if not newrelic_url or not api_key:
        return {"ok": False, "summary": "newrelic_url and newrelic_api_key are required."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_NEWRELIC)
    ) as client:
        response = await client.get(
            f"{newrelic_url}/v2/users.json",
            headers={"Api-Key": api_key, "Accept": "application/json"},
        )
    if response.status_code >= 400:
        return http_status_failure("New Relic", response.status_code)
    return connection_success("Connected to New Relic.")


async def test_splunk_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    splunk_url = str(config.get("splunk_url") or "").strip().rstrip("/")
    token = str(config.get("splunk_token") or "").strip()
    username = str(config.get("splunk_username") or "").strip()
    password = str(config.get("splunk_password") or "").strip()
    if not splunk_url:
        return {"ok": False, "summary": "splunk_url is required."}
    headers = {"Accept": "application/json"}
    auth = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif username and password:
        auth = (username, password)
    else:
        return {"ok": False, "summary": "Either splunk_token or splunk_username/splunk_password are required."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_SPLUNK)
    ) as client:
        response = await client.get(
            f"{splunk_url}/services/server/info",
            headers=headers,
            params={"output_mode": "json"},
            auth=auth,
        )
    if response.status_code >= 400:
        return http_status_failure("Splunk", response.status_code)
    payload = response.json()
    entries = payload.get("entry") or []
    server_version = ((entries[0].get("content") or {}).get("version")) if entries else None
    return connection_success("Connected to Splunk.", version=server_version)
