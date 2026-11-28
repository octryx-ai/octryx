"""Confluence page listing helpers."""

from typing import Any

import httpx

from ._confluence_access import (
    ancestor_ids_of,
    confluence_auth_headers,
    confluence_client,
    normalize_page_rules,
    normalize_space_rules,
    page_allowed,
    space_allowed,
)
from ._confluence_descendants import (
    collect_child_pages_recursive,
    ensure_page_versions,
    fetch_descendant_pages_paginated,
)
from ._confluence_limits import effective_confluence_list_limit
from .context import ToolContext


def effective_confluence_timeout(context: ToolContext, params: dict[str, Any] | None = None) -> float:
    params = params or {}
    raw_timeout = params.get("request_timeout_seconds")
    if raw_timeout in (None, ""):
        raw_timeout = context.project_config.get("confluence_request_timeout_seconds")
    try:
        timeout = float(raw_timeout)
    except (TypeError, ValueError):
        timeout = 30.0
    return max(3.0, min(timeout, 120.0))


def _listing_request_kwargs(context: ToolContext) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"headers": {"Accept": "application/json", **confluence_auth_headers(context)}}
    return kwargs


async def _list_allowed_pages(
    *,
    context: ToolContext,
    confluence_url: str,
    requested_space: str,
    limit: int,
    include_versions: bool,
) -> dict[str, Any] | None:
    page_rules = [rule for rule in normalize_page_rules(context.project_config) if rule.get("enabled", True)]
    if requested_space:
        page_rules = [
            rule
            for rule in page_rules
            if not rule.get("space_key") or rule.get("space_key", "").lower() == requested_space.lower()
        ]
        if any(rule["whole_space"] for rule in page_rules):
            return None  # a whole space: listed like a space, its excludes applied per page
    whole_spaces = [rule["space_key"] for rule in page_rules if rule["whole_space"]]
    page_rules = [rule for rule in page_rules if not rule["whole_space"]]
    if not page_rules and not whole_spaces:
        return None

    pages_by_id: dict[str, dict[str, Any]] = {}
    listing_complete = True
    for rule in page_rules:
        page_id = str(rule.get("id") or "")
        if page_id:
            pages_by_id[page_id] = {
                "id": page_id,
                "title": rule.get("title"),
                "space_key": rule.get("space_key"),
                "enabled": True,
                "include_children": bool(rule.get("include_children", False)),
                "version": None,
            }

    if len(pages_by_id) >= limit:
        if include_versions and confluence_url:
            request_kwargs = _listing_request_kwargs(context)
            timeout = effective_confluence_timeout(context)
            async with httpx.AsyncClient(**confluence_client(context, timeout)) as client:
                await ensure_page_versions(client, confluence_url, request_kwargs, pages_by_id)
        return {"pages": list(pages_by_id.values())[:limit], "listing_complete": False, **_whole(whole_spaces)}

    descendant_roots = [rule for rule in page_rules if rule.get("include_children") and rule.get("id")]
    if descendant_roots and confluence_url:
        request_kwargs = _listing_request_kwargs(context)
        async with httpx.AsyncClient(**confluence_client(context, effective_confluence_timeout(context))) as client:
            for rule in descendant_roots:
                try:
                    descendant_pages, descendants_complete = await fetch_descendant_pages_paginated(
                        client,
                        confluence_url,
                        request_kwargs,
                        root_page_id=str(rule["id"]),
                        limit=limit,
                        include_versions=include_versions,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        raise
                    descendant_pages = await collect_child_pages_recursive(
                        client,
                        confluence_url,
                        request_kwargs,
                        root_page_id=str(rule["id"]),
                        limit=limit,
                    )
                    descendants_complete = len(descendant_pages) < limit
                listing_complete = listing_complete and descendants_complete
                for page in descendant_pages:
                    page_id = str(page.get("id") or "")
                    page_title = page.get("title")
                    page_space = (page.get("space") or {}).get("key") or rule.get("space_key")
                    if page_allowed(
                        context,
                        page_id=page_id,
                        space_key=page_space,
                        ancestor_ids=ancestor_ids_of(page),
                    ):
                        pages_by_id[page_id] = {
                            "id": page_id,
                            "title": page_title,
                            "space_key": page_space,
                            "type": page.get("type"),
                            "version": (page.get("version") or {}).get("number"),
                        }
            if include_versions and pages_by_id:
                await ensure_page_versions(client, confluence_url, request_kwargs, pages_by_id)

    return {"pages": list(pages_by_id.values()), "listing_complete": listing_complete, **_whole(whole_spaces)}


def _whole(spaces: list[str]) -> dict[str, Any]:
    return {"whole_spaces": spaces} if spaces else {}


async def _list_pages_from_root(
    *,
    context: ToolContext,
    confluence_url: str,
    requested_root_page_id: str,
    limit: int,
    include_versions: bool,
) -> dict[str, Any]:
    request_kwargs = _listing_request_kwargs(context)
    async with httpx.AsyncClient(**confluence_client(context, effective_confluence_timeout(context))) as client:
        root_response = await client.get(
            f"{confluence_url}/rest/api/content/{requested_root_page_id}",
            params={"expand": "space,version,ancestors"},
            **request_kwargs,
        )
        root_response.raise_for_status()
        root_payload = root_response.json()
        # The root's real space and path decide, never the requested or first allowed space; its pages are in it.
        root_space = str((root_payload.get("space") or {}).get("key") or "")
        root_ancestors = ancestor_ids_of(root_payload)
        root_page = {
            "id": root_payload.get("id"),
            "title": root_payload.get("title"),
            "space_key": root_space,
            "type": root_payload.get("type"),
            "version": (root_payload.get("version") or {}).get("number") if include_versions else None,
        }
        if not page_allowed(
            context,
            page_id=str(root_page.get("id") or ""),
            space_key=root_space,
            ancestor_ids=root_ancestors,
        ):
            # A refused root lists nothing below it: no id or title of its descendants leaves the tool.
            return {"error": f"Confluence page {requested_root_page_id} is not allowed for this project"}

        pages = [root_page]
        remaining = max(limit - len(pages), 0)
        descendant_pages: list[dict[str, Any]] = []
        descendants_complete = True
        if remaining:
            try:
                descendant_pages, descendants_complete = await fetch_descendant_pages_paginated(
                    client,
                    confluence_url,
                    request_kwargs,
                    root_page_id=requested_root_page_id,
                    limit=remaining,
                    include_versions=include_versions,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise
                descendant_pages = await collect_child_pages_recursive(
                    client,
                    confluence_url,
                    request_kwargs,
                    root_page_id=requested_root_page_id,
                    limit=remaining,
                    root_ancestors=root_ancestors,
                )
                descendants_complete = len(descendant_pages) < remaining

        for page in descendant_pages:
            page_space = (page.get("space") or {}).get("key") or root_space
            if not page_allowed(
                context,
                page_id=str(page.get("id") or ""),
                space_key=page_space,
                ancestor_ids=ancestor_ids_of(page),
            ):
                continue
            pages.append(
                {
                    "id": page.get("id"),
                    "title": page.get("title"),
                    "space_key": page_space,
                    "type": page.get("type"),
                    "version": (page.get("version") or {}).get("number") if include_versions else None,
                }
            )

    listing_complete = remaining > 0 and descendants_complete
    if remaining == 0:
        listing_complete = False
    return {
        "pages": pages,
        "listing_complete": listing_complete,
        "root_page_id": requested_root_page_id,
    }


async def _list_pages_from_space(
    *,
    context: ToolContext,
    confluence_url: str,
    space_key: str,
    limit: int,
    include_versions: bool,
) -> dict[str, Any]:
    request_kwargs = _listing_request_kwargs(context)
    async with httpx.AsyncClient(**confluence_client(context, effective_confluence_timeout(context))) as client:
        response = await client.get(
            f"{confluence_url}/rest/api/content",
            params={
                "spaceKey": space_key,
                "limit": limit,
                "expand": "version,ancestors" if include_versions else "ancestors",
            },
            **request_kwargs,
        )
        response.raise_for_status()
        payload = response.json()

    pages = [
        {
            "id": page.get("id"),
            "title": page.get("title"),
            "space_key": (page.get("space") or {}).get("key", space_key),
            "type": page.get("type"),
            "version": (page.get("version") or {}).get("number"),
        }
        for page in payload.get("results", [])
        if page_allowed(
            context,
            page_id=str(page.get("id") or ""),
            space_key=(page.get("space") or {}).get("key", space_key),
            ancestor_ids=ancestor_ids_of(page),
        )
    ]
    return {"pages": pages, "listing_complete": len(payload.get("results", [])) < limit}


async def list_confluence_pages(params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    confluence_url = str(context.project_config.get("confluence_url") or "").strip().rstrip("/")
    requested_space = str(params.get("space_key") or "").strip()
    requested_root_page_id = str(
        params.get("root_page_id") or context.project_config.get("confluence_root_page_id") or ""
    ).strip()
    limit = effective_confluence_list_limit(
        params.get("limit"),
        context,
        root_page_id=requested_root_page_id,
        force_requested_limit=bool(params.get("force_requested_limits")),
    )
    include_versions = bool(params.get("include_versions"))

    allowed_pages = await _list_allowed_pages(
        context=context,
        confluence_url=confluence_url,
        requested_space=requested_space,
        limit=limit,
        include_versions=include_versions,
    )
    if allowed_pages is not None:
        return allowed_pages

    if not confluence_url:
        return {"error": "No Confluence URL configured for this project"}

    space_rules = [rule for rule in normalize_space_rules(context.project_config) if rule.get("enabled", True)]
    if requested_space and not space_allowed(context, requested_space):
        return {"error": f"Space {requested_space} is not allowed for this project"}
    if not space_rules:
        return {"error": "No Confluence spaces or pages are allowed for this project"}

    if requested_root_page_id:
        return await _list_pages_from_root(
            context=context,
            confluence_url=confluence_url,
            requested_root_page_id=requested_root_page_id,
            limit=limit,
            include_versions=include_versions,
        )

    space_key = requested_space or space_rules[0]["space_key"]

    return await _list_pages_from_space(
        context=context,
        confluence_url=confluence_url,
        space_key=space_key,
        limit=limit,
        include_versions=include_versions,
    )
