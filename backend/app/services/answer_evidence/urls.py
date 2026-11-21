"""URL extraction and comparison for the answer evidence guard.

Structural only: markdown links and bare ``http(s)`` URLs are found by their syntax, and two URLs
are the same source when they match after normalization (scheme and host lowercased, fragment and
trailing slash dropped). Dropping the fragment means a citation of ``page`` for evidence from
``page#section`` is the same page, not an invented one.

One closed internal route is recognized as well, by its own exact validator: the authenticated original of one
Knowledge source revision (``knowledge_original_links``). No other relative or ``/api`` path is ever a source.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from .knowledge_original_links import knowledge_original_url

# HTTP(S) or the closed Knowledge original route; validation follows extraction.
MARKDOWN_LINK = re.compile(r"\[([^\[\]\n]{0,300})\]\(((?:https?://|/api/v1/workspaces/)[^\s<>()]{1,2048})\)")
_BARE_URL = re.compile(r"https?://[^\s<>\"'`\[\]{}|\\^]{1,2048}")
_TRAILING_PUNCTUATION = ".,;:!?'\"*_"
MAX_URL_CHARS = 2048


def _trimmed(raw: str) -> str:
    url = raw
    while url:
        if url[-1] in _TRAILING_PUNCTUATION:
            url = url[:-1]
        elif url[-1] == ")" and url.count("(") < url.count(")"):
            url = url[:-1]
        else:
            break
    return url


def normalize_url(raw: object) -> str | None:
    """The comparable form of a governed openable URL, or ``None`` when ``raw`` is not one."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_URL_CHARS:
        return None
    candidate = _trimmed(raw.strip())
    if candidate.startswith("/"):
        return knowledge_original_url(candidate)
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return None
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def urls_in_text(text: str) -> list[str]:
    """Every http(s) URL written in ``text`` (link targets and bare URLs), normalized, in order."""
    found: list[str] = []
    for match in _BARE_URL.finditer(text or ""):
        normalized = normalize_url(match.group(0))
        if normalized is not None:
            found.append(normalized)
    for match in MARKDOWN_LINK.finditer(text or ""):
        if match.group(2).startswith("/"):
            normalized = normalize_url(match.group(2))
            if normalized is not None:
                found.append(normalized)
    return found


def link_target(cite_as: object) -> str | None:
    """The normalized target of a ``[label](url)`` citation, or ``None`` for a plain label."""
    if not isinstance(cite_as, str):
        return None
    match = MARKDOWN_LINK.search(cite_as)
    return normalize_url(match.group(2)) if match else None


def unique(urls: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(urls))


__all__ = ["MARKDOWN_LINK", "link_target", "normalize_url", "unique", "urls_in_text"]
