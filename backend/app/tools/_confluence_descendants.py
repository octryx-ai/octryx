"""Internal descendant-listing helpers for Confluence page browsing."""

from typing import Any

import httpx

MAX_CONFLUENCE_PAGE_BATCH = 200


async def collect_child_pages_recursive(
    client: httpx.AsyncClient,
    confluence_url: str,
    request_kwargs: dict[str, Any],
    *,
    root_page_id: str,
    limit: int,
    root_ancestors: list[str] | None = None,
) -> list[dict[str, Any]]:
    """The pages below the root, breadth first; each with its space and its path (``ancestors``).

    The path starts with ``root_ancestors`` (the root's own ancestors), so an exclude above the root (a subtree or
    whole-space entry's) still applies on this fallback path.
    """
    collected: list[dict[str, Any]] = []
    queue = [root_page_id]
    seen: set[str] = set()
    # The path down to each page, so the page allowlist sees each page's ancestors (subtree excludes).
    chain: dict[str, list[str]] = {root_page_id: list(root_ancestors or [])}

    while queue and len(collected) < limit:
        current_page_id = queue.pop(0)
        if current_page_id in seen:
            continue
        seen.add(current_page_id)
        response = await client.get(
            f"{confluence_url}/rest/api/content/{current_page_id}/child/page",
            params={"limit": limit, "expand": "space"},
            **request_kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        for page in payload.get("results", []):
            page_id = str(page.get("id") or "")
            if not page_id or page_id in seen:
                continue
            chain[page_id] = [*chain.get(current_page_id, []), current_page_id]
            if not page.get("ancestors"):
                page = {**page, "ancestors": [{"id": ancestor} for ancestor in chain[page_id]]}
            collected.append(page)
            queue.append(page_id)
            if len(collected) >= limit:
                break
    return collected


async def fetch_descendant_pages_paginated(
    client: httpx.AsyncClient,
    confluence_url: str,
    request_kwargs: dict[str, Any],
    *,
    root_page_id: str,
    limit: int,
    include_versions: bool,
) -> tuple[list[dict[str, Any]], bool]:
    pages: list[dict[str, Any]] = []
    start = 0
    listing_complete = True

    while len(pages) < limit:
        batch_limit = min(MAX_CONFLUENCE_PAGE_BATCH, limit - len(pages))
        response = await client.get(
            f"{confluence_url}/rest/api/content/{root_page_id}/descendant/page",
            params={
                "start": start,
                "limit": batch_limit,
                # The page's own space: a descendant never inherits a requested or allowed space.
                "expand": "space,ancestors,version" if include_versions else "space,ancestors",
            },
            **request_kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", []) or []
        pages.extend(results)

        size = int(payload.get("size") or len(results))
        batch_returned = len(results)
        next_link = (payload.get("_links") or {}).get("next")

        if batch_returned == 0:
            break
        if next_link:
            start += size
            continue
        if batch_returned < batch_limit:
            break

        listing_complete = False
        break

    return pages[:limit], listing_complete


async def fetch_child_page_summaries(
    client: httpx.AsyncClient,
    confluence_url: str,
    request_kwargs: dict[str, Any],
    *,
    page_id: str,
    limit: int,
    include_versions: bool = True,
) -> tuple[list[dict[str, Any]], bool]:
    response = await client.get(
        f"{confluence_url}/rest/api/content/{page_id}/child/page",
        params={
            "limit": max(1, min(limit, MAX_CONFLUENCE_PAGE_BATCH)),
            **({"expand": "space,version"} if include_versions else {"expand": "space"}),
        },
        **request_kwargs,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", []) or []
    is_complete = not bool((payload.get("_links") or {}).get("next")) and len(results) < limit
    return results[:limit], is_complete


async def ensure_page_versions(
    client: httpx.AsyncClient,
    confluence_url: str,
    request_kwargs: dict[str, Any],
    pages_by_id: dict[str, dict[str, Any]],
) -> None:
    for page_id, page in pages_by_id.items():
        if isinstance(page.get("version"), int):
            continue
        response = await client.get(
            f"{confluence_url}/rest/api/content/{page_id}",
            params={"expand": "version"},
            **request_kwargs,
        )
        response.raise_for_status()
        payload = response.json()
        page["version"] = (payload.get("version") or {}).get("number")
