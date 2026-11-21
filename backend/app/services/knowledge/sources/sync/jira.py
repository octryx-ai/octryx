"""Jira issues of the configured projects, on the Source Sync contract.

**Listing.** Server/Data Center: ``GET /rest/api/2/search``, paged by offset (the token is the offset).
Jira Cloud (``*.atlassian.net``), which withdrew ``/search``: ``POST /rest/api/3/search/jql`` with explicit
fields, paged by Jira's opaque ``nextPageToken`` (the token is ``c:<nextPageToken>``). Both list
``project in (...)``, optionally narrowed by an author-supplied JQL filter that is always ANDed
inside the project clause, so it can never widen the scope, ordered by creation
(``jira_releases.search_issue_page``). The issue's ``updated`` time is the version marker and the stable issue
``id`` (not the key, which changes when an issue moves) is the external id.

**ACL.** An issue with an issue security level is readable by fewer people than the project
audience, so it is restricted; the level's name is kept in the ACL facet. Its members cannot be
listed through the Server/DC REST API without administrator rights, so :meth:`expand_acl` answers
``None`` and such an issue stays withheld even where the Workspace enforces source ACLs (5b).

**Content.** The search already returns every rendered field, so ``fetch`` renders the listed issue
(``jira_render.py``) without another request: Markdown with fixed headings, ingested in-process.
**Releases.** With an active release configuration, the pass continues after the last issue page
with the projects' versions, one release-notes source per version (``jira_releases.py``).

The connector only reads; it has no code path that writes to Jira.
"""

from __future__ import annotations

import httpx

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_JIRA
from .....tools.jira_impl._jira_allowlist import issue_in_allowlist
from .....tools.jira_impl._jira_jql_confine import UnsafeJqlError, confine_jql
from .connections import SourceConnection
from .contract import (
    REASON_SOURCE_CONTRACT_VIOLATION,
    AclExpansion,
    AclFacet,
    ConnectorError,
    ItemContent,
    ListingPage,
    SourceItem,
)
from .http import SourceReader
from .jira_release_config import ReleaseConfig
from .jira_releases import JiraReleaseLister, reader_is_cloud, search_issue_page
from .jira_render import SEARCH_FIELDS, render_issue
from .source_dates import source_date

MAX_TITLE_CHARS = 300
# Jira Cloud page tokens are opaque; the listing token carries one behind this prefix.
CLOUD_TOKEN_PREFIX = "c:"


def build_jql(project_keys: tuple[str, ...], jql_filter: str | None) -> str:
    projects = ", ".join(f'"{key}"' for key in project_keys)
    clause = f"project in ({projects})"
    if jql_filter:
        # The filter can never break out of the project clause (quote/paren-aware); a stored
        # filter with a backslash outside quotes is a contract violation, never sent.
        try:
            clause = confine_jql(jql_filter, clause)
        except UnsafeJqlError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    return f"{clause} ORDER BY created ASC, key ASC"


def _with_project(fields: str) -> str:
    return fields if "project" in fields.split(",") else f"{fields},project"


class JiraConnector:
    kind = CONNECTOR_KIND_JIRA
    requires_parser = False

    def __init__(
        self,
        connection: SourceConnection,
        *,
        project_keys: tuple[str, ...],
        jql_filter: str | None = None,
        releases: ReleaseConfig | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._reader = SourceReader(connection, transport=transport)
        self._jql = build_jql(project_keys, jql_filter)
        self._project_keys = project_keys
        self._releases = JiraReleaseLister(self._reader, releases, jql_filter=jql_filter) if releases else None
        # Issue id -> (key, fields) of the listing pages of this run; ``fetch`` renders from here.
        self._listed: dict[str, tuple[str, dict]] = {}

    async def list_items(self, token: str | None, *, limit: int) -> ListingPage:
        if JiraReleaseLister.owns_token(token):
            if self._releases is None:
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
            page = await self._releases.list_page(token, limit=limit)
            return ListingPage(items=page.items, next_token=page.next_token, skipped=page.skipped)
        cloud = reader_is_cloud(self._reader)
        if token is not None and (token.startswith(CLOUD_TOKEN_PREFIX) is not cloud):
            # A token of the other API (or a foreign one) never pages on.
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        cursor = token.removeprefix(CLOUD_TOKEN_PREFIX) if token is not None else None
        issues, next_cursor = await search_issue_page(
            # ``project`` lets the allowlist filter cross-check every returned key.
            self._reader, self._jql, fields=_with_project(SEARCH_FIELDS), size=limit, cursor=cursor
        )
        # Only issues of the configured projects are listed, whatever the query returned.
        # A malformed entry still fails the page in ``_header`` (contract violation).
        items = [
            self._header(issue) for issue in issues
            if not isinstance(issue, dict) or issue_in_allowlist(issue, self._project_keys)
        ]
        if next_cursor is not None:
            next_token: str | None = f"{CLOUD_TOKEN_PREFIX}{next_cursor}" if cloud else next_cursor
        else:
            # The issues are done: the releases follow in the same pass, when configured.
            next_token = self._releases.first_token() if self._releases else None
        return ListingPage(items=tuple(items), next_token=next_token)

    def _header(self, issue: object) -> SourceItem:
        if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        issue_id, key, fields = str(issue.get("id") or ""), str(issue.get("key") or ""), issue["fields"]
        updated = fields.get("updated")
        if not issue_id.isdigit() or not key or not isinstance(updated, str):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        self._listed[issue_id] = (key, fields)
        security = fields.get("security")
        if security is not None:
            level = str(security.get("name") or security.get("id") or "") if isinstance(security, dict) else ""
            acl = AclFacet.restricted("issue_security_level", (f"level:{level}",) if level else ())
        else:
            acl = AclFacet.scope()
        summary = " ".join(str(fields.get("summary") or "").split())
        title = f"{key}: {summary}"[:MAX_TITLE_CHARS] if summary else key
        return SourceItem(issue_id, title, f"{self._reader.base_url}/browse/{key}", updated, acl,
                          source_changed_at=source_date(updated))

    async def expand_acl(self, acl: AclFacet) -> AclExpansion | None:
        # An issue security level's members are not readable without Jira administrator rights.
        return None

    async def fetch(self, item: SourceItem) -> ItemContent:
        if self._releases is not None and JiraReleaseLister.owns_item(item.external_id):
            return self._releases.fetch(item)
        listed = self._listed.get(item.external_id)
        if listed is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        key, fields = listed
        return ItemContent(data=render_issue(key, fields).encode("utf-8"), media_type="text/markdown")


__all__ = ["JiraConnector", "build_jql"]
