"""The closed Knowledge original route as an answer-evidence link; recognition grants no access.

Exactly one internal route is recognized next to the repository viewer: the authenticated original of one
source revision, ``/api/v1/workspaces/{workspace}/knowledge/sources/{source}/revisions/{revision}/original``
(``api/routes/knowledge_source_originals.py``). Opening it still authorizes the Workspace, the source's
visibility and its tombstone state on every request (``ledger/original.read_original``).

Closed by construction: a relative path only (no scheme, host or credentials), the canonical lower-case
Workspace UUID, lower-case UUIDs for source and revision (hyphenated, or the 32-hex form), the exact
``/original`` suffix, and no query, fragment, percent-encoding or dot segment. Every other ``/api`` path is
not a source. Building and recognizing share this module, so a link the tools emit is one the guard accepts.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit
from uuid import UUID

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ID = rf"(?:{_UUID}|[0-9a-f]{{32}})"
_ORIGINAL_PATH = re.compile(
    rf"/api/v1/workspaces/(?P<workspace>{_UUID})/knowledge/sources/(?P<source>{_ID})"
    rf"/revisions/(?P<revision>{_ID})/original"
)
ORIGINAL_ROUTE_PREFIX = "/api/v1/workspaces/"


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def knowledge_original_url(raw: str) -> str | None:
    """``raw`` when it is exactly the governed original route of one revision, else ``None``."""
    if not isinstance(raw, str) or "%" in raw or "\\" in raw or ".." in raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    if parts.scheme or parts.netloc or parts.query or parts.fragment or "?" in raw or "#" in raw:
        return None
    match = _ORIGINAL_PATH.fullmatch(parts.path)
    if match is None or not all(_is_uuid(value) for value in match.groupdict().values()):
        return None
    return parts.path


def knowledge_original_path(workspace_id: object, source_id: object, revision_id: object) -> str | None:
    """The original route of one revision in its own Workspace, or ``None`` when the identity is not exact."""
    if not all(isinstance(value, str) and value for value in (workspace_id, source_id, revision_id)):
        return None
    return knowledge_original_url(
        f"{ORIGINAL_ROUTE_PREFIX}{workspace_id}/knowledge/sources/{source_id}/revisions/{revision_id}/original"
    )


__all__ = ["ORIGINAL_ROUTE_PREFIX", "knowledge_original_path", "knowledge_original_url"]
