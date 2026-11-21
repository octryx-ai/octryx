"""Confluence read results as evidence: every page names its openable source.

A page's URL comes from the one builder the Source Sync uses (
``services/knowledge/sources/sync/confluence.py`` ``canonical_page_url``): the page's own
``_links.webui`` on the configured base when known, else the ``viewpage.action`` form.
No configured base or no numeric page id: no source fields (``tools/evidence_fields``).
"""

from __future__ import annotations

from typing import Any

from app.services.knowledge.sources.sync.confluence_links import canonical_page_url

from .evidence_fields import http_url, with_source


def page_url(confluence_url: str, page_id: object, *, webui: object = None) -> str | None:
    if http_url(str(confluence_url or "").rstrip("/")) is None:
        return None
    return http_url(canonical_page_url(confluence_url, page_id, webui=webui))


def page_webui(page: dict[str, Any]) -> object:
    """The page's ``_links.webui`` as the API returned it (validated by the shared builder)."""
    links = page.get("_links")
    return links.get("webui") if isinstance(links, dict) else None


def with_page_source(item: dict[str, Any], confluence_url: str, *, webui: object = None) -> dict[str, Any]:
    """Source fields from the shared builder, with the page's ``_links.webui`` when known."""
    link = page_url(confluence_url, item.get("id"), webui=webui if webui is not None else page_webui(item))
    return with_source(item, title=item.get("title") or item.get("id"), url=link)


def with_recorded_page_source(item: dict[str, Any]) -> dict[str, Any]:
    """A Source Sync ledger page: its stored origin link (recorded by the sync from the connector base)."""
    return with_source(item, title=item.get("title") or item.get("id"), url=http_url(item.get("url")))


__all__ = ["page_url", "with_page_source", "with_recorded_page_source"]
