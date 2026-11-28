"""The pinned source read of one published page: the legacy-view profile, its refusals and its document."""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass


def view_document(title: str, source_url: str, body: str) -> bytes:
    escaped = html.escape(title)
    # The canonical link is part of the content: a rename or move is a new revision with its new origin.
    canonical = html.escape(source_url, quote=True)
    document = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{escaped}</title>'
        f'<link rel="canonical" href="{canonical}"></head>'
        f"<body><h1>{escaped}</h1>{body}</body></html>"
    )
    return document.encode("utf-8")


# The pinned read uses the sync's own v1 ``body.view`` endpoint, so its bytes compare with the ingested
# revision. Cloud only, one endpoint, no fallback; a ``version.number`` other than the published one is refused, and
# a removed v1 endpoint (404/410) refuses as ``legacy_view_unavailable``.

LEGACY_VIEW_PROFILE: dict[str, str] = {
    "id": "confluence-cloud-legacy-view@2026-10-13",
    "endpoint": "GET /rest/api/content/{id}",
    "expand": "body.view,version",
    "representation": "view",
    "removal_dependency": "Confluence Cloud v1 content GET deprecation; replace with a v2 body-format=view sync",
}

PINNED_REFUSED_INSTANCE = "profile_instance_unsupported"
PINNED_REFUSED_SHAPE = "profile_shape_violation"
PINNED_REFUSED_VERSION = "version_mismatch"
PINNED_REFUSED_READ = "legacy_view_unavailable"


class PinnedViewRefusedError(Exception):
    def __init__(self, reason: str, *, source_reason: str = "", fetched_version: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.source_reason = source_reason
        self.fetched_version = fetched_version


@dataclass(frozen=True, slots=True)
class PinnedView:
    page_id: str
    version: int
    title: str
    source_url: str
    read_base: str
    view_raw_digest: str
    document_digest: str
    document_sha256: str
    profile: str


def sha256_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _profile_view(payload: dict, page_id: str) -> tuple[str, int]:
    version_info = payload.get("version")
    version = version_info.get("number") if isinstance(version_info, dict) else None
    view = (payload.get("body") or {}).get("view") if isinstance(payload.get("body"), dict) else None
    shaped = (
        str(payload.get("id") or "") == page_id
        and payload.get("type") == "page"
        and payload.get("status") == "current"
        and type(version) is int
        and version >= 1
        and isinstance(view, dict)
        and view.get("representation") == LEGACY_VIEW_PROFILE["representation"]
        and isinstance(view.get("value"), str)
    )
    if not shaped:
        raise PinnedViewRefusedError(PINNED_REFUSED_SHAPE)
    return view["value"], version

