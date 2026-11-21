"""The pinned source read of one published page: the legacy-view profile, its refusals and its document."""

from __future__ import annotations

import hashlib
import html
from dataclasses import dataclass


def view_document(title: str, source_url: str, body: str) -> bytes:
    """The generated HTML document of one page (title + canonical link + ``body.view``), as ingested."""
    escaped = html.escape(title)
    # The canonical link is part of the content: a rename or move is a new revision with its new origin.
    canonical = html.escape(source_url, quote=True)
    document = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{escaped}</title>'
        f'<link rel="canonical" href="{canonical}"></head>'
        f"<body><h1>{escaped}</h1>{body}</body></html>"
    )
    return document.encode("utf-8")


# --- Pinned source read: the bounded, owned legacy-view compatibility profile ----------------------------------
#
# The documentation provenance check must prove that the bytes Knowledge ingested are the generated document of
# exactly the published version. The Source Sync ingests the legacy v1 ``body.view`` (the connector's ``fetch``), so the
# pinned read uses the same endpoint and representation: a Cloud v2 view would be another representation, never
# comparable to the ingested revision byte-for-byte, and moving the sync itself to v2 is a separate, global rewrite.
#
# The profile is therefore explicit, versioned and bounded:
# - endpoint: ``GET {base}/rest/api/content/{id}?expand=body.view,version`` on an Atlassian **Cloud** instance
#   (host ``*.atlassian.net``, base path ``/wiki``); no Data Center claim, no other endpoint, no fallback;
# - shape: ``id`` equals the page, ``type`` is ``page``, ``status`` is ``current``, ``version.number`` is a positive
#   int, ``body.view.representation`` is ``view`` and ``body.view.value`` a string; anything else is refused;
# - pin: ``version.number`` must equal the published version, else the read is refused (no historical read: a
#   newer version means the page moved on, an older one that the read lags; both refuse and relist);
# - evidence: the sync's ``body.view`` read is observed on a real tenant; the ``version`` expansion shape is
#   checked on the tenant before the profile is relied on;
# - removal dependency: Atlassian deprecates the v1 content GET (Cloud access catalog; removal policy announced for
#   31 Mar 2025). A removed endpoint answers 404/410 and the read refuses (``legacy_view_unavailable``); the
#   replacement is a Source Sync that ingests v2 ``body-format=view``, after which this
#   profile is deleted together with the sync's v1 ``fetch``.

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
    """The pinned read refused: ``reason`` is one of the ``PINNED_REFUSED_*`` values, never response text."""

    def __init__(self, reason: str, *, source_reason: str = "", fetched_version: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.source_reason = source_reason
        self.fetched_version = fetched_version


@dataclass(frozen=True, slots=True)
class PinnedView:
    """What the pinned read observed. Digests are ``sha256:<hex>``; ``document_sha256`` is bare hex, the
    ledger's ``content_sha256`` form."""

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
    """``(body.view value, version number)`` of a profile-shaped answer, else :class:`PinnedViewRefusedError`."""
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

