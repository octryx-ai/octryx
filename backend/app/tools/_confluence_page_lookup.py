"""Internal page lookup helpers for Confluence tools."""

from typing import Any

import httpx

from ._confluence_access import ancestor_ids_of


class MalformedConfluenceAnswerError(ValueError):
    """A successful HTTP answer whose content is not the documented page shape: never proof of anything."""


async def fetch_page_record(
    client: httpx.AsyncClient,
    confluence_url: str,
    request_kwargs: dict[str, Any],
    *,
    page_id: str,
    title: str,
    space_key: str,
    expand: str,
) -> dict[str, Any] | None:
    if page_id:
        response = await client.get(
            f"{confluence_url}/rest/api/content/{page_id}",
            params={"expand": expand},
            **request_kwargs,
        )
        response.raise_for_status()
        page = response.json()
        if not isinstance(page, dict) or not str(page.get("id") or "").strip():
            raise MalformedConfluenceAnswerError("the page answer carries no page")
        return page

    response = await client.get(
        f"{confluence_url}/rest/api/content",
        params={
            "title": title,
            "spaceKey": space_key,
            "expand": expand,
            "limit": 1,
        },
        **request_kwargs,
    )
    response.raise_for_status()
    # Only a valid, empty result list proves that no page has the title: anything else is no answer.
    payload = response.json()
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not all(
            isinstance(item, dict) and str(item.get("id") or "").strip() for item in results):
        raise MalformedConfluenceAnswerError("the title search answer is not a list of pages")
    return results[0] if results else None


def extract_page_metadata(
    page: dict[str, Any],
    *,
    fallback_page_id: str = "",
    fallback_title: str = "",
    fallback_space_key: str = "",
) -> dict[str, Any]:
    return {
        "resolved_id": str(page.get("id") or fallback_page_id),
        "resolved_title": page.get("title") or fallback_title,
        "resolved_space": (page.get("space") or {}).get("key") or fallback_space_key,
        "ancestor_ids": ancestor_ids_of(page),
        "version": (page.get("version") or {}).get("number"),
        "updated_by": (page.get("version") or {}).get("by"),
        "updated_when": (page.get("version") or {}).get("when"),
        "created_by": (page.get("history") or {}).get("createdBy"),
        "created_when": (page.get("history") or {}).get("createdDate"),
        "body": (((page.get("body") or {}).get("storage") or {}).get("value")) or "",
        # The canonical link's path; validated by the shared link builder.
        "webui": (page.get("_links") or {}).get("webui") if isinstance(page.get("_links"), dict) else None,
    }
