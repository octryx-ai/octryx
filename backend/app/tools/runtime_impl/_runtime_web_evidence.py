"""Web results carry their source in the same shape as the Knowledge evidence.

Every ``web_search`` / ``codesearch`` hit and every ``web_fetch`` page gets ``source_title``,
``source_url`` and a ready ``cite_as`` markdown link (``tools/evidence_fields.py``). The model cites a
web fact by copying ``cite_as``, and the answer evidence guard (``services/answer_evidence``) reads
the same fields. ``source_url`` is the absolute http(s) URL or ``null``; without one, ``cite_as`` is
the plain label.
"""

from __future__ import annotations

import html
import re
from typing import Any

from ..evidence_fields import source_fields

_HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


def with_hit_sources(body: dict[str, Any]) -> dict[str, Any]:
    """A search answer whose every result names its source."""
    results = body.get("results")
    if isinstance(results, list):
        body["results"] = [
            {**hit, **source_fields(title=hit.get("title"), url=hit.get("url"))} if isinstance(hit, dict) else hit
            for hit in results
        ]
    return body


def html_title(raw: str, content_type: str) -> str:
    """The page's ``<title>``, for HTML responses only."""
    if "html" not in str(content_type or "").lower() and "<html" not in raw[:2000].lower():
        return ""
    match = _HTML_TITLE.search(raw[:200_000])
    return html.unescape(match.group(1)) if match else ""


__all__ = [
    "html_title",
    "with_hit_sources",
]
