"""Bitbucket Cloud (bitbucket.org, REST API 2.0) behind the Bitbucket tools.

A Bitbucket connection names where Bitbucket runs (``bitbucket_deployment``, see
``named_connections/descriptors/scm.py``). For ``cloud``:

- REST calls go to ``https://api.bitbucket.org/2.0`` with HTTP basic auth: the Atlassian account email
  (``bitbucket_username``) and an Atlassian API token with Bitbucket scopes (``bitbucket_token``);
- Git over HTTPS uses ``https://bitbucket.org/<workspace>/<repo>.git`` with the fixed user
  ``x-bitbucket-api-token-auth`` and the same token (Atlassian's rule for API tokens);
- a repository is ``<workspace>/<repo slug>`` (the tools' ``project_key`` / ``repo_slug``), always lower case.

Every call goes through the pinned ``bitbucket`` egress transport without following redirects. A refused call is a
:class:`CloudApiError` carrying the HTTP status and Bitbucket's own error message (bounded); never a header, URL
or credential. The Server/Data Center paths of the tools stay as they are; a Cloud connection never reaches them
(``_bitbucket_internal_network`` refuses a ``/rest/`` path on a Cloud connection).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from app.tools.context import ToolContext

from ...services.outbound_egress import CONNECTION_BITBUCKET, egress_transport
from ..connectors.credential_boundary import connector_secret_value

DEPLOYMENT_FIELD = "bitbucket_deployment"
DEPLOYMENT_CLOUD = "cloud"
API_BASE = "https://api.bitbucket.org/2.0"
WEB_BASE = "https://bitbucket.org"
GIT_USERNAME = "x-bitbucket-api-token-auth"
CLOUD_HOSTS = frozenset({"bitbucket.org", "api.bitbucket.org"})
TIMEOUT_SECONDS = 30
MAX_ERROR_CHARS = 300


class CloudApiError(Exception):
    """A refused or failed Bitbucket Cloud call: its HTTP status (0: no call) and a bounded, credential-free text."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def cloud_failure(error: CloudApiError) -> dict[str, Any]:
    """A tool's answer for a refused Bitbucket Cloud call: Bitbucket's own message and the HTTP status."""
    return {"error": error.message, "status_code": error.status, "deployment": DEPLOYMENT_CLOUD}


def is_cloud(config: dict[str, Any] | None) -> bool:
    return str((config or {}).get(DEPLOYMENT_FIELD) or "").strip().lower() == DEPLOYMENT_CLOUD


def cloud_context(context: ToolContext) -> bool:
    return is_cloud(getattr(context, "project_config", None))


def repo_path(workspace: str, slug: str) -> str:
    return f"/repositories/{quote(workspace.strip().lower(), safe='')}/{quote(slug.strip().lower(), safe='')}"


def clone_url(workspace: str, slug: str) -> str:
    return f"{WEB_BASE}/{workspace.strip().lower()}/{slug.strip().lower()}.git"


def web_url(workspace: str, slug: str) -> str:
    return f"{WEB_BASE}/{workspace.strip().lower()}/{slug.strip().lower()}"


async def cloud_credentials(context: ToolContext) -> tuple[str, str]:
    """``(account email, API token)`` of the connection; a password is never used for Bitbucket Cloud."""
    config = context.project_config or {}
    host = (urlsplit(str(config.get("bitbucket_url") or "").strip()).hostname or "").lower()
    if host not in CLOUD_HOSTS:  # also a project-default entry, which the named-connection check never sees
        raise CloudApiError(0, "A Bitbucket Cloud connection's URL is https://bitbucket.org.")
    email = str(config.get("bitbucket_username") or "").strip()
    token = str(config.get("bitbucket_token") or "").strip()
    if email and not token:
        token = str(await connector_secret_value(context, connector_name="bitbucket", field_name="bitbucket_token")
                    or "").strip()
    if not email or not token:
        raise CloudApiError(0, "The Bitbucket Cloud connection needs the account email and its API token.")
    return email, token


def _transport() -> httpx.AsyncBaseTransport:
    return egress_transport(CONNECTION_BITBUCKET)


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = None
    error = body.get("error") if isinstance(body, dict) else None
    message = str(error.get("message") or "") if isinstance(error, dict) else ""
    return (message or f"Bitbucket Cloud answered HTTP {response.status_code}.")[:MAX_ERROR_CHARS]


async def cloud_request(
    context: ToolContext,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    """One REST 2.0 call on the connection's account; the JSON answer (``{}`` when empty). A write to a repository
    the Workspace registered read-only raises ``RepositoryWriteRefusedError`` before any request."""
    from ._bitbucket_write_gate import require_rest_write_allowed

    await require_rest_write_allowed(context, method, path)
    auth = await cloud_credentials(context)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False, transport=_transport()) as client:
        response = await client.request(
            method, f"{API_BASE}{path}", params=params, json=payload, auth=auth,
            headers={"Accept": "application/json"},
        )
    if response.status_code >= 400:
        from ..connectors.common import log_refusal

        log_refusal(CONNECTION_BITBUCKET, method, f"{API_BASE}{path}", response)
        raise CloudApiError(response.status_code, _error_text(response))
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise CloudApiError(response.status_code, "Bitbucket Cloud answered without JSON.") from None


__all__ = [
    "API_BASE",
    "DEPLOYMENT_CLOUD",
    "DEPLOYMENT_FIELD",
    "GIT_USERNAME",
    "WEB_BASE",
    "CloudApiError",
    "clone_url",
    "cloud_context",
    "cloud_failure",
    "cloud_credentials",
    "cloud_request",
    "is_cloud",
    "repo_path",
    "web_url",
]
