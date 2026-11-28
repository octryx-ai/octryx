"""Paging through one ServiceNow Scripted REST endpoint (``servicenow_scripted``). Failures are closed codes, never a
body or a value."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx

from .servicenow_scripted import (
    CODE_HTTP_STATUS,
    CODE_UNEXPECTED_SHAPE,
    CODE_UNREACHABLE,
    MAX_PAGE_SIZE,
    ScriptedEndpointError,
    ScriptedPage,
    parse_page,
)


async def _page(client: httpx.AsyncClient, base_url: str, path: str, table: str, *, size: int, offset: int,
                headers: Mapping[str, str] | None) -> ScriptedPage:
    try:
        response = await client.get(
            f"{base_url.rstrip('/')}{path}", params={"sysparm_limit": size, "sysparm_offset": offset},
            headers=dict(headers or {}),
        )
    except httpx.HTTPError:
        raise ScriptedEndpointError(CODE_UNREACHABLE) from None
    if response.status_code != 200:
        raise ScriptedEndpointError(CODE_HTTP_STATUS, http_status=response.status_code)
    try:
        payload = response.json() if response.content else None
    except ValueError:
        raise ScriptedEndpointError(CODE_UNEXPECTED_SHAPE) from None
    return parse_page(payload, table)


async def fetch_records(
    client: httpx.AsyncClient, base_url: str, path: str, table: str, *, limit: int, page_size: int,
    headers: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    records: list[dict[str, Any]] = []
    total: int | None = None
    offset = 0
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    while len(records) < limit:
        size = min(page_size, limit - len(records))
        page = await _page(client, base_url, path, table, size=size, offset=offset, headers=headers)
        total = page.total if page.total is not None else total
        records.extend(page.records[:size])
        offset += len(page.records)
        if len(page.records) < size or (total is not None and offset >= total):
            break
    return records[:limit], total


async def fetch_matching_records(
    client: httpx.AsyncClient, base_url: str, path: str, table: str, *, limit: int, page_size: int,
    keep: Callable[[Mapping[str, Any]], bool], max_scanned: int, headers: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    kept: list[dict[str, Any]] = []
    offset = 0
    size = max(1, min(page_size, MAX_PAGE_SIZE))
    while len(kept) < limit and offset < max_scanned:
        page = await _page(client, base_url, path, table, size=size, offset=offset, headers=headers)
        kept.extend(record for record in page.records[:size] if keep(record))
        offset += len(page.records)
        if len(page.records) < size or (page.total is not None and offset >= page.total):
            return kept[:limit], True
    return kept[:limit], False


__all__ = ["fetch_matching_records", "fetch_records"]
