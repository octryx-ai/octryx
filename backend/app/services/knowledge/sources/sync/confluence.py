"""Confluence pages of the configured spaces, on the Source Sync contract."""

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
        # One request, no fallback: the pinned profile answers at the pinned version or the read is refused.
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
