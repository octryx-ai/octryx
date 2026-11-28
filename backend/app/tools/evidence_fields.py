"""Source fields of evidence-bearing tool results, in the Knowledge evidence shape."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit

from ..services.knowledge.retrieval.locator import markdown_citation

MAX_TITLE_CHARS = 200


def _http_parts(url: object):
    value = str(url or "").strip()
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    return parts


def http_url(url: object) -> str | None:
    return str(url).strip() if _http_parts(url) is not None else None


def url_host(url: object) -> str | None:
    parts = _http_parts(url)
    return parts.hostname.lower() if parts is not None else None


def source_fields(*, title: object, url: object) -> dict[str, Any]:
    source_url = http_url(url)
    source_title = " ".join(str(title or "").split())[:MAX_TITLE_CHARS] or source_url or "Source"
    return {
        "source_title": source_title,
        "source_url": source_url,
        "cite_as": markdown_citation(source_title, source_url, ()),
    }


def item_url(base_url: object, *segments: object, query: str = "", fragment: str = "") -> str | None:
    base = http_url(str(base_url or "").rstrip("/"))
    parts = [str(segment).strip() for segment in segments]
    if base is None or not parts or not all(parts):
        return None
    path = "/".join(quote(part, safe="/") for part in parts)
    return f"{base}/{path}" + (f"?{query}" if query else "") + (f"#{fragment}" if fragment else "")


def known_web_url(candidate: object, base_url: object) -> str | None:
    host = url_host(base_url)
    return http_url(candidate) if host is not None and url_host(candidate) == host else None


def vendor_web_url(candidate: object, hosts: frozenset[str]) -> str | None:
    return http_url(candidate) if url_host(candidate) in hosts else None


def with_source(item: dict[str, Any], *, title: object, url: str | None) -> dict[str, Any]:
    return {**item, **source_fields(title=title, url=url)} if url else item


__all__ = [
    "http_url",
    "item_url",
    "known_web_url",
    "source_fields",
    "url_host",
    "vendor_web_url",
    "with_source",
]
