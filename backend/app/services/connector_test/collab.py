from __future__ import annotations

from typing import Any

from app.services.connector_auth.atlassian_modes import (
    BITBUCKET,
    CONFLUENCE,
    JIRA,
    SCHEME_OIDC,
    AtlassianAuthConfigError,
)
from app.services.connector_auth.atlassian_validation import (
    auth_failure_hint,
    confluence_cloud_url_problem,
    jira_cloud_url_problem,
    validate_auth_config,
)
from app.services.outbound_egress import (
    CONNECTION_BITBUCKET,
    CONNECTION_CONFLUENCE,
    CONNECTION_GITHUB,
    CONNECTION_JIRA,
    egress_transport,
)

from ...tools.jira_impl._jira_api_versions import api_versions, remember_api_version
from ..connector_auth.atlassian import request_auth, resolve_credential
from ..connector_auth.oidc_client_credentials import CODE_CONNECTOR_UNAUTHORIZED, OidcTokenError
from ..github_url import normalize_github_api_base_url
from .failure import connection_success, http_status_failure

# One fixed summary per probed endpoint; the account behind the token is never echoed.
JIRA_SUCCESS_SUMMARIES = {
    "/rest/api/3/myself": "Connected to Jira (REST API 3).",
    "/rest/api/2/myself": "Connected to Jira (REST API 2).",
}


def _auth_problem(connector: str, config: dict[str, Any]) -> dict[str, Any] | None:
    try:
        validate_auth_config(connector, config)
    except AtlassianAuthConfigError as exc:
        return {"ok": False, "summary": str(exc)}
    return None


def _auth_failure(service: str, connector: str, status_code: int, config: dict[str, Any]) -> dict[str, Any]:
    result = http_status_failure(service, status_code)
    if status_code in (401, 403):
        hint = auth_failure_hint(connector, config)
        result["summary"] = f"{result['summary']} {hint}"
        result["auth_hint"] = hint
        credential = resolve_credential(connector, config)
        if credential is not None and credential.scheme == SCHEME_OIDC:
            result["auth_code"] = CODE_CONNECTOR_UNAUTHORIZED
    return result


def _token_failure(service: str, error: OidcTokenError) -> dict[str, Any]:
    return {"ok": False, "summary": f"{service}: {error}", "auth_code": error.code, "auth_hint": str(error)}


async def test_jira_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    jira_url = str(config.get("jira_url") or "").strip().rstrip("/")
    problem = _auth_problem(JIRA, config)
    if problem:
        return problem
    url_problem = jira_cloud_url_problem(jira_url)
    if url_problem:
        return {"ok": False, "summary": f"Jira: {url_problem}"}
    credential = resolve_credential(JIRA, config)
    if not jira_url or credential is None:
        return {
            "ok": False,
            "summary": "jira_url, jira_auth_mode and the credential of that authentication mode are required.",
        }

    headers = {"Accept": "application/json", **credential.headers()}
    # The API version this instance answered last time first (Data Center has no v3: a 404 every check before).
    endpoints = [f"/rest/api/{version}/myself" for version in api_versions(jira_url)]
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_JIRA), auth=request_auth(JIRA, config)
    ) as client:
        for endpoint in endpoints:
            try:
                response = await client.get(f"{jira_url}{endpoint}", headers=headers)
            except OidcTokenError as error:
                return _token_failure("Jira", error)
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                return _auth_failure("Jira", JIRA, response.status_code, config)
            remember_api_version(jira_url, endpoint.split("/")[3])
            return connection_success(JIRA_SUCCESS_SUMMARIES[endpoint])
    return {"ok": False, "summary": "Jira /myself endpoint was not found."}


async def _test_bitbucket_cloud(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    email = str(config.get("bitbucket_username") or "").strip()
    token = str(config.get("bitbucket_token") or "").strip()
    if not email or not token:
        return {"ok": False, "summary": "Bitbucket Cloud needs the Atlassian account email and an API token."}
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=False, transport=egress_transport(CONNECTION_BITBUCKET)
    ) as client:
        response = await client.get("https://api.bitbucket.org/2.0/user", headers={"Accept": "application/json"},
                                    auth=(email, token))
    if response.status_code == 401:
        return {"ok": False, "summary": "Bitbucket Cloud refused the sign-in: check the account email and that the "
                                        "API token was created with Bitbucket scopes."}
    if response.status_code >= 400:
        return http_status_failure("Bitbucket Cloud", response.status_code)
    return connection_success("Connected to Bitbucket Cloud.")


async def test_bitbucket_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    problem = _auth_problem(BITBUCKET, config)
    if problem:
        return problem
    if str(config.get("bitbucket_deployment") or "").strip().lower() == "cloud":
        return await _test_bitbucket_cloud(config, httpx_module=httpx_module)
    bitbucket_url = str(config.get("bitbucket_url") or "").strip().rstrip("/")
    credential = resolve_credential(BITBUCKET, config)
    if not bitbucket_url or credential is None:
        return {
            "ok": False,
            "summary": "bitbucket_url, bitbucket_auth_mode and the credential of that authentication mode are "
            "required.",
        }

    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET),
        auth=request_auth(BITBUCKET, config),
    ) as client:
        try:
            response = await client.get(
                f"{bitbucket_url}/rest/api/1.0/application-properties",
                headers={"Accept": "application/json", **credential.headers()},
            )
        except OidcTokenError as error:
            return _token_failure("Bitbucket", error)
    if response.status_code >= 400:
        return _auth_failure("Bitbucket", BITBUCKET, response.status_code, config)
    payload = response.json()
    return connection_success("Connected to Bitbucket.", version=payload.get("version"))


async def test_github_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    github_url = normalize_github_api_base_url(config.get("github_url"))
    github_token = str(config.get("github_token") or "").strip()
    if not github_url or not github_token:
        return {
            "ok": False,
            "summary": "github_url and github_token are required.",
        }

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx_module.AsyncClient(
        timeout=15, follow_redirects=True, transport=egress_transport(CONNECTION_GITHUB)
    ) as client:
        response = await client.get(f"{github_url}/user", headers=headers)
    if response.status_code >= 400:
        return http_status_failure("GitHub", response.status_code)
    return connection_success("Connected to GitHub.")


async def test_confluence_connection(config: dict[str, Any], *, httpx_module: Any) -> dict[str, Any]:
    confluence_url = str(config.get("confluence_url") or "").strip().rstrip("/")
    problem = _auth_problem(CONFLUENCE, config)
    if problem:
        return problem
    credential = resolve_credential(CONFLUENCE, config)
    if not confluence_url or credential is None:
        return {
            "ok": False,
            "summary": "confluence_url, confluence_auth_mode and the credential of that authentication mode are "
            "required.",
        }
    cloud_url_problem = confluence_cloud_url_problem(confluence_url)
    if cloud_url_problem:
        # Refused, never rewritten: the admin sets the /wiki URL explicitly.
        return {"ok": False, "summary": cloud_url_problem}

    async with httpx_module.AsyncClient(
        timeout=15,
        follow_redirects=True,
        transport=egress_transport(CONNECTION_CONFLUENCE),
        auth=request_auth(CONFLUENCE, config),
    ) as client:
        try:
            response = await client.get(
                f"{confluence_url}/rest/api/space",
                headers={"Accept": "application/json", **credential.headers()},
                params={"limit": 1},
            )
        except OidcTokenError as error:
            return _token_failure("Confluence", error)
    if response.status_code >= 400:
        return _auth_failure("Confluence", CONFLUENCE, response.status_code, config)
    payload = response.json()
    return connection_success("Connected to Confluence.", counts={"visible_spaces_in_sample": payload.get("size")})
