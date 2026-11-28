"""One level of a Confluence space's page tree, for the admin page picker."""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import HTTPException

from app.services.connector_auth.atlassian_modes import CONFLUENCE

from ..connector_auth.atlassian import auth_headers, request_auth
from ..connector_auth.oidc_client_credentials import OidcTokenError
from ..outbound_egress import CONNECTION_CONFLUENCE, egress_transport
from .rules import PAGE_ID, SPACE_KEY

DEFAULT_LIMIT = 25
MAX_LIMIT = 50
MAX_START = 10_000
TIMEOUT_SECONDS = 20.0
MAX_TITLE_CHARS = 300

CODE_INVALID_REQUEST = "page_tree_request_invalid"
CODE_UNAUTHORIZED = "confluence_unauthorized"
CODE_NOT_FOUND = "confluence_page_not_found"
CODE_UNAVAILABLE = "confluence_unavailable"

_WHITESPACE = re.compile(r"\s+")


def refuse(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def tree_request(space_key: object, parent_id: object, start: object, limit: object) -> tuple[str, str, int, int]:
    space = str(space_key or "").strip()
    parent = str(parent_id or "").strip()
    if not SPACE_KEY.fullmatch(space) or (parent and not PAGE_ID.fullmatch(parent)):
        raise refuse(422, CODE_INVALID_REQUEST, "A space key and, for child pages, a numeric page id are required.")
    try:
        begin = int(start or 0)
        size = int(limit or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        raise refuse(422, CODE_INVALID_REQUEST, "start and limit must be numbers.") from None
    if not 0 <= begin <= MAX_START or not 1 <= size <= MAX_LIMIT:
        raise refuse(422, CODE_INVALID_REQUEST, f"start must be 0..{MAX_START} and limit 1..{MAX_LIMIT}.")
    return space, parent, begin, size


def _failure(status_code: int) -> HTTPException:
    if status_code in (401, 403):
        return refuse(502, CODE_UNAUTHORIZED, "Confluence refused the connection's account for this space or page.")
    if status_code == 404:
        return refuse(404, CODE_NOT_FOUND,
                      "Confluence does not know this space or page, or this account cannot see it.")
    return refuse(502, CODE_UNAVAILABLE, f"Confluence answered HTTP {status_code}.")


def _node(page: dict[str, Any]) -> dict[str, str] | None:
    page_id = str(page.get("id") or "").strip()
    if not PAGE_ID.fullmatch(page_id):
        return None
    title = _WHITESPACE.sub(" ", str(page.get("title") or "")).strip()[:MAX_TITLE_CHARS]
    return {"id": page_id, "title": title or f"Page {page_id}"}


async def read_level(
    config: dict[str, Any],
    *,
    space_key: str,
    parent_id: str,
    start: int,
    limit: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    base = str(config.get("confluence_url") or "").strip().rstrip("/")
    if not base:
        raise refuse(409, CODE_UNAVAILABLE, "The connection that serves this space has no Confluence URL.")
    if parent_id:
        path = f"/rest/api/content/{parent_id}/child/page"
        params: dict[str, Any] = {"start": start, "limit": limit, "expand": "space"}
    else:
        path = f"/rest/api/space/{space_key}/content/page"
        params = {"depth": "root", "start": start, "limit": limit}
    headers = {"Accept": "application/json", **auth_headers(CONFLUENCE, config)}
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=True,
            transport=transport or egress_transport(CONNECTION_CONFLUENCE), auth=request_auth(CONFLUENCE, config),
        ) as client:
            response = await client.get(f"{base}{path}", params=params, headers=headers)
    except OidcTokenError as error:
        raise refuse(502, error.code, str(error)) from None
    except httpx.HTTPError:
        raise refuse(502, CODE_UNAVAILABLE, "Confluence could not be reached.") from None
    if response.status_code >= 400:
        raise _failure(response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise refuse(502, CODE_UNAVAILABLE, "Confluence answered with something that is not JSON.") from None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        raise refuse(502, CODE_UNAVAILABLE, "Confluence answered without a page list.")
    pages = []
    for page in results[:limit]:
        if not isinstance(page, dict):
            continue
        space = (page.get("space") or {}).get("key") if isinstance(page.get("space"), dict) else None
        if parent_id and space and str(space).lower() != space_key.lower():
            continue  # a child page reported in another space is not this space's page
        node = _node(page)
        if node is not None:
            pages.append(node)
    links = payload.get("_links") if isinstance(payload.get("_links"), dict) else {}
    more = bool(links.get("next")) or len(results) >= limit
    next_start = start + len(results) if more and results and start + len(results) <= MAX_START else None
    return {"space_key": space_key, "parent_id": parent_id or None, "pages": pages, "start": start,
            "next_start": next_start}


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "read_level", "tree_request"]
