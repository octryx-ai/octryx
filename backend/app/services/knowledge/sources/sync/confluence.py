"""Confluence pages of the configured spaces, on the Source Sync contract.

**Listing.** ``GET /rest/api/content`` per space (``type=page``, ``status=current``). The next page
is the source's own ``_links.next``, followed verbatim relative to the base URL (Confluence
Cloud pages by opaque cursor, Server/Data Center by offset; only ``limit`` is set to the runner's
page size). The token is ``"<space index>:<next link>"``; a unit starts at the offset token
``"<space index>:0"``. Each header carries the page version number
as its marker, the canonical deep link and the page's read restrictions (``expand``).

**Canonical link** (:func:`canonical_page_url`, shared with the Confluence tools): ``_links.base``
plus the page's ``_links.webui`` when the source reports them (Cloud and Data Center both do), else
the configured base URL plus ``/pages/viewpage.action?pageId=``. The link is also written into the
fetched document, so a renamed or moved page becomes a new revision with its new origin.

**Changes** (:meth:`ConfluenceConnector.list_changed_items`). An incremental run asks CQL
search, per space, for the pages modified since an instant (``lastmodified >= "<instant>"``,
Cloud and Data Center syntax), paged by ``_links.next`` like the listing.

**Page trees** (``confluence_scope.py``). After the whole spaces, each configured page tree is one
more listing unit: CQL search ``space = … and type = page and (id = <root> or ancestor = <root>)``,
for changes with ``and lastmodified >= …``, paged like the rest. The token's index runs over spaces,
then trees.

**Page allowlist**. When the connection's ``confluence_allowed_pages`` has entries, a
listed page is kept only if the same decision the Confluence tools use allows it
(``services/confluence_pages/rules.py``: own entry, subtree with its excludes, whole space), from the page's
id, title, the unit's space and its ``ancestors``. A page it does not allow is not listed, so a page that
was ingested before is retired when the pass completes, like a page moved out of a page tree.

When the rules change, a newly excluded page is therefore retired at the end of the next *completed header
pass*, not by the change listing: a rule change does not modify the page, so the CQL change listing never
lists it. Every scheduled run continues the header pass after its change listing, so a source whose pass
completes within one run (the common case) retires such pages on the next scheduled run; a source larger than
one run's page bound does so when its open pass completes. Retiring them earlier would need either a header
listed as "deleted" (which the run report would wrongly call removed at the source) or the ancestors of every
ingested page (not stored), so it is deliberately not done.

**ACL.** A page is readable by the whole space audience only when neither it nor any ancestor has a
read (view) restriction; view restrictions are inherited in Confluence. The page's own restrictions
come with the listing; an ancestor's are known from the listing when it was listed first, and are
otherwise looked up once per run (``/restriction/byOperation/read``). A lookup that fails leaves the
ACL ``unknown``, so the page is never ingested on a guess. A restricted page's users and groups are
expanded to member addresses by ``confluence_acl.py`` when the Workspace enforces source ACLs (5b).

**Content.** ``body.view``: the rendered HTML, with macros expanded and headings, lists and tables
intact. It goes through the Docling sandbox, so spans follow the page's sections and tables. The
storage format was not chosen because its ``ac:``/``ri:`` macro markup is not HTML a parser
understands, and an HTML-to-text flattening would lose the table structure.

**Pinned read** (:meth:`ConfluenceConnector.fetch_pinned_view`). The documentation provenance check reads one
published page once more at exactly its published version, through a bounded and owned legacy-view
compatibility profile (``LEGACY_VIEW_PROFILE`` below: Cloud only, one endpoint, a strict response shape, a
version pin with refusal, no fallback, and a recorded removal dependency). The sync's own ``fetch`` is unchanged.
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_CONFLUENCE
from .confluence_acl import ConfluenceAclExpander
from .confluence_listing import ConfluenceListing
from .confluence_pinned import (
    LEGACY_VIEW_PROFILE,
    PINNED_REFUSED_INSTANCE,
    PINNED_REFUSED_READ,
    PINNED_REFUSED_SHAPE,
    PINNED_REFUSED_VERSION,
    PinnedView,
    PinnedViewRefusedError,
    _profile_view,
    sha256_digest,
    view_document,
)
from .connections import SourceConnection
from .contract import REASON_SOURCE_CONTRACT_VIOLATION, AclExpansion, AclFacet, ConnectorError, ItemContent, SourceItem
from .http import SourceReader


class ConfluenceConnector(ConfluenceListing):
    kind = CONNECTOR_KIND_CONFLUENCE
    requires_parser = True

    def __init__(
        self,
        connection: SourceConnection,
        *,
        spaces: tuple[str, ...],
        page_trees: tuple[dict[str, str], ...] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._reader = SourceReader(connection, transport=transport)
        self._spaces = spaces
        self._trees = page_trees
        # Listing units in token order: whole spaces, then page trees.
        self._units = len(spaces) + len(page_trees)
        # Page id -> its own read principals, from listings and lookups of this run.
        self._restrictions: dict[str, tuple[str, ...]] = {}
        self._acl_expander = ConfluenceAclExpander(self._reader)
        self._page_rules = connection.page_rules
        self._allowed_spaces = connection.allowed_scopes or frozenset()

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        return await self._acl_expander.expand(acl)

    async def fetch(self, item: SourceItem) -> ItemContent:
        payload = await self._reader.get_json(f"/rest/api/content/{item.external_id}", {"expand": "body.view"})
        body = ((payload.get("body") or {}).get("view") or {}).get("value")
        if not isinstance(body, str):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return ItemContent(data=view_document(item.title, item.source_url, body), media_type="text/html")

    async def fetch_pinned_view(self, page_id: str, *, version: int) -> PinnedView:
        """The pinned source read of one published page at exactly ``version`` (legacy-view profile, below).

        Only the documentation provenance check calls this; the sync's own :meth:`fetch` is unchanged. One request, no
        fallback: the profile's endpoint answers in the profile's shape at the pinned version, or the read is
        refused with a :class:`PinnedViewRefusedError` reason. The generated document is built exactly as
        :meth:`fetch` builds it, so its digest is comparable to the ingested revision's ``content_sha256``.
        """
        identifier = str(page_id or "").strip()
        if not identifier.isdigit() or type(version) is not int or version < 1:
            raise PinnedViewRefusedError(PINNED_REFUSED_SHAPE)
        if not legacy_view_instance_admitted(self._reader.base_url):
            raise PinnedViewRefusedError(PINNED_REFUSED_INSTANCE)
        try:
            payload = await self._reader.get_json(
                f"/rest/api/content/{identifier}", {"expand": LEGACY_VIEW_PROFILE["expand"]}
            )
        except ConnectorError as error:
            raise PinnedViewRefusedError(PINNED_REFUSED_READ, source_reason=error.reason) from None
        body, fetched = _profile_view(payload, identifier)
        if fetched != version:
            raise PinnedViewRefusedError(PINNED_REFUSED_VERSION, fetched_version=fetched)
        links = payload.get("_links") if isinstance(payload.get("_links"), dict) else {}
        try:
            title, link = self._title_and_link(payload, identifier, links.get("base"))
        except ConnectorError:
            raise PinnedViewRefusedError(PINNED_REFUSED_SHAPE) from None
        document = view_document(title, link, body)
        return PinnedView(
            page_id=identifier,
            version=fetched,
            title=title,
            source_url=link,
            read_base=self._reader.base_url,
            view_raw_digest=sha256_digest(body.encode("utf-8")),
            document_digest=sha256_digest(document),
            document_sha256=hashlib.sha256(document).hexdigest(),
            profile=LEGACY_VIEW_PROFILE["id"],
        )


#: The hosts the profile admits (Atlassian Cloud). A module constant on purpose: tests point it at their stub host.
LEGACY_VIEW_PROFILE_HOST_SUFFIXES: tuple[str, ...] = (".atlassian.net",)
LEGACY_VIEW_PROFILE_CONTEXT = "/wiki"


def legacy_view_instance_admitted(base_url: str) -> bool:
    """The profile's instance rule: an Atlassian Cloud host under ``/wiki`` (no Data Center claim)."""
    parts = urlsplit(str(base_url or ""))
    host = (parts.hostname or "").lower()
    return (
        parts.scheme == "https"
        and any(host.endswith(suffix) for suffix in LEGACY_VIEW_PROFILE_HOST_SUFFIXES)
        and parts.path.rstrip("/") == LEGACY_VIEW_PROFILE_CONTEXT
    )


__all__ = [
    "ConfluenceConnector",
    "legacy_view_instance_admitted",
]
