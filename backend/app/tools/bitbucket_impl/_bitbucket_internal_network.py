"""Bitbucket HTTP helpers."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_BITBUCKET, egress_transport
from app.tools.context import ToolContext

from ._bitbucket_cloud import cloud_context
from ._bitbucket_internal_core import _bitbucket_base_url, _bitbucket_http_auth
from ._bitbucket_write_gate import require_rest_write_allowed


def _server_only(context: ToolContext, path: str) -> None:
    if cloud_context(context) and path.startswith("/rest/"):
        raise ValueError("This Bitbucket operation is not available for Bitbucket Cloud connections yet.")


async def _bitbucket_json_get(
    context: ToolContext,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _server_only(context, path)
    bitbucket_url = _bitbucket_base_url(context)
    auth = await _bitbucket_http_auth(context)
    request_kwargs: dict[str, Any] = {"headers": {"Accept": "application/json"}, "params": params or {}}
    if auth:
        request_kwargs["auth"] = auth

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)) as client:
        response = await client.get(f"{bitbucket_url}{path}", **request_kwargs)
        response.raise_for_status()
        return response.json()


async def _bitbucket_json_post(
    context: ToolContext,
    path: str,
    *,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    _server_only(context, path)
    await require_rest_write_allowed(context, "POST", path)  # a read-only registered repository is never written
    bitbucket_url = _bitbucket_base_url(context)
    auth = await _bitbucket_http_auth(context)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
    if auth:
        request_kwargs["auth"] = auth

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)) as client:
        response = await client.post(f"{bitbucket_url}{path}", **request_kwargs)
        response.raise_for_status()
        body = response.json() if response.content else None
        return body, response.status_code


async def _bitbucket_json_put(
    context: ToolContext,
    path: str,
    *,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    _server_only(context, path)
    await require_rest_write_allowed(context, "PUT", path)
    bitbucket_url = _bitbucket_base_url(context)
    auth = await _bitbucket_http_auth(context)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    request_kwargs: dict[str, Any] = {"headers": headers, "json": payload}
    if auth:
        request_kwargs["auth"] = auth

    async with httpx.AsyncClient(timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_BITBUCKET)) as client:
        response = await client.put(f"{bitbucket_url}{path}", **request_kwargs)
        response.raise_for_status()
        body = response.json() if response.content else None
        return body, response.status_code
