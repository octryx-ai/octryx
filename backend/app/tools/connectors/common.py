"""Shared helpers for external connector tools.

Every HTTP helper sends through the pinned egress transport of a connection type
(``services/outbound_egress``) and takes that type as a required ``connection`` keyword: there
is no default rule. Each connector module binds its own type once (:func:`connection_http_json`
and its siblings), so the tool applies the same rule as the connection test, Source Sync and the
services of that connection.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from app.services.outbound_egress import connection_rule, egress_transport

from ...services.request_analysis import (
    effective_limit_from_request_analysis,
    extract_explicit_limit,
    request_analysis_from_snapshot,
)
from ..context import ToolContext

logger = logging.getLogger(__name__)


def _string(value: Any) -> str:
    return str(value or "").strip()


def _normalize_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        if not raw.strip():
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
        return [item.strip() for item in raw.replace(",", "\n").splitlines() if item.strip()]
    if isinstance(raw, list):
        items: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                name = _string(
                    item.get("name")
                    or item.get("repository")
                    or item.get("project")
                    or item.get("id")
                    or item.get("path")
                    or item.get("site_path")
                    or item.get("service")
                )
                if name and item.get("enabled", True):
                    items.append(name)
            else:
                name = _string(item)
                if name:
                    items.append(name)
        return items
    return []


def _limit(
    context: ToolContext | None,
    params: dict[str, Any],
    default: int = 20,
    maximum: int = 100,
    param_name: str = "limit",
) -> int:
    if context is not None:
        analysis = request_analysis_from_snapshot(context.turn_context_snapshot)
        if not analysis and context.current_user_message:
            analysis = {
                "explicit_limit_requested": extract_explicit_limit(context.current_user_message) is not None,
                "explicit_limit_value": extract_explicit_limit(context.current_user_message),
            }
        explicit_requested = bool(analysis.get("explicit_limit_requested"))
        if explicit_requested:
            return effective_limit_from_request_analysis(
                snapshot=context.turn_context_snapshot,
                fallback_user_message=context.current_user_message,
                requested_limit=params.get(param_name),
                default_if_unspecified=default,
                hard_max=maximum,
            )
        if context.current_user_message:
            return maximum
        try:
            value = int(params.get(param_name))
            if value >= 1:
                return min(value, maximum)
        except Exception:
            return default
        return default
    try:
        value = int(params.get(param_name) or default)
    except Exception:
        value = default
    return max(1, min(value, maximum))


def _headers_with_bearer(token: str | None, *, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = dict(extra or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _headers_with_basic(
    username: str | None, password: str | None, *, extra: dict[str, str] | None = None
) -> dict[str, str]:
    headers = dict(extra or {})
    if username and password:
        auth = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        headers["Authorization"] = f"Basic {auth}"
    return headers


async def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    connection: str,
    auth: httpx.Auth | None = None,
) -> Any:
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, transport=egress_transport(connection), auth=auth
    ) as client:
        response = await client.request(method, url, headers=headers, params=params, json=json_body)
    if response.status_code >= 400:
        log_refusal(connection, method, url, response)
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def log_refusal(connection: str, method: str, url: str, response: httpx.Response) -> None:
    """A provider's non-2xx answer, with its own error body (never the headers or the query string).

    the log showed only "POST …/refs/branches 400 Bad Request"; why the provider
    refused (the branch existed) was nowhere."""
    logger.warning("connector.http_refused", extra={
        "connection": connection, "method": method, "path": httpx.URL(url).path,
        "status_code": response.status_code, "body": response.text})


async def _http_form_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    form_data: dict[str, Any] | None = None,
    timeout: int = 30,
    connection: str,
) -> Any:
    request_headers = dict(headers or {})
    request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, transport=egress_transport(connection)) as client:
        response = await client.request(method, url, headers=request_headers, params=params, data=form_data)
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


async def _http_response(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    connection: str,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, transport=egress_transport(connection)) as client:
        response = await client.request(method, url, headers=headers, params=params, json=json_body)
    return response


async def _http_text(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 30,
    connection: str,
) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, transport=egress_transport(connection)) as client:
        response = await client.request(method, url, headers=headers, params=params, json=json_body)
    response.raise_for_status()
    return response.text


def _connection_bound(helper_name: str, connection: str):
    """The helper ``helper_name`` bound to one connection type, looked up at call time.

    The lookup at call time lets a test replace this module's helper once for every connector bound to it;
    ``egress_connection`` names the connection the binding is for.
    """
    connection_rule(connection)  # an unclassified type fails at import, not at the first call

    async def _bound(method: str, url: str, **kwargs: Any) -> Any:
        return await globals()[helper_name](method, url, connection=connection, **kwargs)

    _bound.egress_connection = connection
    _bound.__name__ = helper_name
    return _bound


def connection_http_json(connection: str):
    return _connection_bound("_http_json", connection)


def connection_http_form_json(connection: str):
    return _connection_bound("_http_form_json", connection)


def connection_http_response(connection: str):
    return _connection_bound("_http_response", connection)


def connection_http_text(connection: str):
    return _connection_bound("_http_text", connection)
