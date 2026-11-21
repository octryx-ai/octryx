"""Source fields of evidence-bearing tool results, in the Knowledge evidence shape.

Every read result a person could open carries ``source_title``, ``source_url`` and a ready
``cite_as`` markdown link, like a Knowledge passage (``tools/knowledge_evidence/search.py``). The
model cites by copying ``cite_as``; the answer evidence guard (``services/answer_evidence``) reads
the same fields.

URLs are never guessed. A connector item's URL is one of two kinds, both bound to the connector's
own configuration:

- :func:`item_url`: the connector's configured base URL plus the item's key path (a Jira issue's
  ``/browse/KEY``, a Confluence page's ``viewpage.action?pageId=``). Only an absolute http(s) base
  with a host yields one.
- :func:`known_web_url`: a web URL the connector API returned (``html_url``, ``web_url``), accepted
  only when its host is the configured connector host.

No configured base, or a foreign host, means no source fields at all: the item is then not an
openable source, never a constructed one.
"""

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
    """``url`` when it is an absolute http(s) URL with a host, else ``None``."""
    return str(url).strip() if _http_parts(url) is not None else None


def url_host(url: object) -> str | None:
    parts = _http_parts(url)
    return parts.hostname.lower() if parts is not None else None


def source_fields(*, title: object, url: object) -> dict[str, Any]:
    """The three source fields; ``source_url`` null and ``cite_as`` a plain label without a URL."""
    source_url = http_url(url)
    source_title = " ".join(str(title or "").split())[:MAX_TITLE_CHARS] or source_url or "Source"
    return {
        "source_title": source_title,
        "source_url": source_url,
        "cite_as": markdown_citation(source_title, source_url, ()),
    }


def item_url(base_url: object, *segments: object, query: str = "", fragment: str = "") -> str | None:
    """The configured ``base_url`` plus quoted path ``segments``; ``None`` without a valid base or key.

    ``fragment`` is appended verbatim for consoles that route in the fragment (AWS, Azure).
    """
    base = http_url(str(base_url or "").rstrip("/"))
    parts = [str(segment).strip() for segment in segments]
    if base is None or not parts or not all(parts):
        return None
    path = "/".join(quote(part, safe="/") for part in parts)
    return f"{base}/{path}" + (f"?{query}" if query else "") + (f"#{fragment}" if fragment else "")


def known_web_url(candidate: object, base_url: object) -> str | None:
    """``candidate`` when its host is the configured connector host, else ``None``."""
    host = url_host(base_url)
    return http_url(candidate) if host is not None and url_host(candidate) == host else None


def vendor_web_url(candidate: object, hosts: frozenset[str]) -> str | None:
    """``candidate`` when its host is one of a SaaS vendor's fixed web ``hosts``, else ``None``.

    For connectors whose API endpoint is the vendor's fixed public one (Notion, Linear), like
    ``github.com`` for the public GitHub API: the web host is part of the connector, not a guess.
    """
    return http_url(candidate) if url_host(candidate) in hosts else None


def with_source(item: dict[str, Any], *, title: object, url: str | None) -> dict[str, Any]:
    """``item`` plus its source fields when ``url`` is known; unchanged otherwise."""
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
