"""The release phase of a Jira listing pass: one release-notes source per Jira version.

After the issues of a pass, a Jira connector with an active release configuration
(``jira_release_config.py``) lists the versions of every mapped project, in project order, through
``GET /rest/api/2/project/{key}/version`` (paged, ``orderBy=sequence``). The token is
``r:<project index>:<offset>``. For each version:

- **Version.** The name is read as a version with the configured literal prefixes
  (``release_version``); a name that is not a version is reported as skipped
  (``version_name_unrecognized``) and never ingested.
- **Issues.** One page at a time through :func:`search_issue_page`: Server/DC ``GET /rest/api/2/search``
  (``startAt``), Jira Cloud ``POST /rest/api/3/search/jql`` (``nextPageToken``; no ``total``), for
  ``project = KEY AND fixVersion = <id>``, ANDed with the
  connector's own JQL filter, so a release note never shows an issue the issue sync would not.
  Bounded to ``MAX_RELEASE_ISSUES``; the rendering says when that bound cut the list.
- **ACL.** An issue with an issue security level is left out: its members cannot be expanded, so
  it would be withheld as ``restricted_acl`` on its own, and a release note must not carry it into
  the Workspace-wide audience. The release itself is then readable by the whole project audience.
- **Item.** External id ``release-<version id>``, title ``Release <version>``, the version's deep
  link, product = the project's configured product, version = the normalized version, document
  role ``release_notes``. The version marker is the SHA-256 of the rendering, so a release is
  re-ingested exactly when its content changed, and never otherwise.

Only ``GET`` is used (``http.SourceReader``): nothing here can write to Jira.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .....tools.jira_impl._jira_allowlist import issue_in_allowlist
from .....tools.jira_impl._jira_cloud import is_jira_cloud
from .....tools.jira_impl._jira_jql_confine import UnsafeJqlError, confine_jql
from .contract import REASON_SOURCE_CONTRACT_VIOLATION, AclFacet, ConnectorError, ItemContent, SourceItem
from .http import SourceReader
from .jira_release_config import REASON_VERSION_NAME_UNRECOGNIZED, ReleaseConfig, release_version
from .jira_release_render import render_release

RELEASE_TOKEN_PREFIX = "r:"
RELEASE_EXTERNAL_PREFIX = "release-"
RELEASE_DOCUMENT_ROLE = "release_notes"
RELEASE_PAGE_SIZE = 10
ISSUE_PAGE_SIZE = 100
MAX_RELEASE_ISSUES = 500
RELEASE_ISSUE_FIELDS = "summary,description,issuetype,resolution,components,labels,security"
# Bounds an opaque Jira Cloud ``nextPageToken`` kept in a listing cursor.
MAX_CLOUD_PAGE_TOKEN_CHARS = 2048


def version_url(base_url: str, project_key: str, version_id: str) -> str:
    return f"{base_url}/projects/{project_key}/versions/{version_id}"


def release_jql(project_key: str, version_id: str, jql_filter: str | None) -> str:
    clause = f'project = "{project_key}" AND fixVersion = {version_id}'
    if jql_filter:
        # The filter can never break out of the project clause (quote/paren-aware); a stored
        # filter with a backslash outside quotes is a contract violation, never sent.
        try:
            clause = confine_jql(jql_filter, clause)
        except UnsafeJqlError:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION) from None
    return f"{clause} ORDER BY key ASC"


@dataclass(frozen=True, slots=True)
class ReleasePage:
    items: tuple[SourceItem, ...]
    skipped: tuple[tuple[str, str], ...]
    next_token: str | None


def _parse_token(token: str) -> tuple[int, int]:
    parts = token.removeprefix(RELEASE_TOKEN_PREFIX).split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return int(parts[0]), int(parts[1])


def reader_is_cloud(reader: SourceReader) -> bool:
    """A Jira Cloud site (``*.atlassian.net``); the Source Sync connection carries no auth mode."""
    return is_jira_cloud(reader.base_url)


async def search_issue_page(
    reader: SourceReader, jql: str, *, fields: str, size: int, cursor: str | None
) -> tuple[list, str | None]:
    """One page of issues and the cursor of the next one (``None`` at the end), on the site's own API.

    The cursor is the ``startAt`` offset on Server/DC and Jira's opaque ``nextPageToken`` on Cloud. Every
    answer is checked for shape; a contract violation never pages on. An empty page while the source says
    more remain is one too (root decision): the listing can neither page on (it could loop) nor end, because
    an ended listing completes the pass and the runner would retire every issue not yet listed.
    """
    page, next_cursor, more = await _search_issue_page(reader, jql, fields=fields, size=size, cursor=cursor)
    if not page and more:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    return page, next_cursor


async def _search_issue_page(
    reader: SourceReader, jql: str, *, fields: str, size: int, cursor: str | None
) -> tuple[list, str | None, bool]:
    """``search_issue_page`` plus whether the source says more issues remain.

    An empty page never pages on (that could loop), even when the source says more remain; ``more`` lets a
    caller report that stop as a truncation instead of the end.
    """
    if reader_is_cloud(reader):
        body: dict = {"jql": jql, "fields": [name for name in fields.split(",") if name], "maxResults": size}
        if cursor:
            body["nextPageToken"] = cursor
        payload = await reader.post_search_jql(body)
        page, token, is_last = payload.get("issues"), payload.get("nextPageToken"), payload.get("isLast")
        if not isinstance(page, list) or len(page) > size or (is_last is not None and type(is_last) is not bool):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        if token is not None and (type(token) is not str or not token or len(token) > MAX_CLOUD_PAGE_TOKEN_CHARS):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        more = not is_last and token is not None
        return page, (token if more and page else None), more
    if cursor is not None and not cursor.isdigit():
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    start = int(cursor or 0)
    payload = await reader.get_json(
        "/rest/api/2/search", {"jql": jql, "startAt": start, "maxResults": size, "fields": fields}
    )
    page, total = payload.get("issues"), payload.get("total")
    if not isinstance(page, list) or len(page) > size or type(total) is not int:
        raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
    end = start + len(page)
    more = end < total
    return page, (str(end) if more and page else None), more


async def search_release_issues(
    reader: SourceReader, jql: str, *, fields: str, bound: int, project_key: str
) -> tuple[list[tuple[str, dict]], bool]:
    """(key, fields) of up to ``bound`` issues of ``jql``, and whether that is every matching issue.

    The list is complete only when the source says it ended: an empty page while more remain is a truncation.
    Only issues of ``project_key`` are kept (key project, matching ``fields.project``), so
    nothing of another project is rendered or counted, whatever the query returned.
    """
    issues: list[tuple[str, dict]] = []
    cursor: str | None = None
    complete = False
    while len(issues) < bound:
        size = min(ISSUE_PAGE_SIZE, bound - len(issues))
        # ``project`` lets the allowlist filter cross-check every returned key.
        page, cursor, more = await _search_issue_page(reader, jql, fields=f"{fields},project", size=size, cursor=cursor)
        for issue in page:
            key = issue.get("key") if isinstance(issue, dict) else None
            if type(key) is not str or not key or not isinstance(issue.get("fields"), dict):
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
            if issue_in_allowlist(issue, (project_key,)):
                issues.append((key, issue["fields"]))
        if cursor is None:
            complete = not more
            break
    return issues, complete


class JiraReleaseLister:
    """The release phase of one Jira connector's listing pass."""

    def __init__(self, reader: SourceReader, config: ReleaseConfig, *, jql_filter: str | None) -> None:
        self._reader = reader
        self._config = config
        self._jql_filter = jql_filter
        self._rendered: dict[str, bytes] = {}

    @staticmethod
    def first_token() -> str:
        return f"{RELEASE_TOKEN_PREFIX}0:0"

    @staticmethod
    def owns_token(token: str | None) -> bool:
        return token is not None and token.startswith(RELEASE_TOKEN_PREFIX)

    @staticmethod
    def owns_item(external_id: str) -> bool:
        return external_id.startswith(RELEASE_EXTERNAL_PREFIX)

    async def list_page(self, token: str, *, limit: int) -> ReleasePage:
        project_index, offset = _parse_token(token)
        if project_index >= len(self._config.products):
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        project_key, product = self._config.products[project_index]
        size = min(limit, RELEASE_PAGE_SIZE)
        payload = await self._reader.get_json(
            f"/rest/api/2/project/{project_key}/version",
            {"startAt": offset, "maxResults": size, "orderBy": "sequence"},
        )
        values, is_last = payload.get("values"), payload.get("isLast")
        if not isinstance(values, list) or len(values) > size or type(is_last) is not bool:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        items: list[SourceItem] = []
        skipped: list[tuple[str, str]] = []
        for value in values:
            version_id = str(value.get("id") or "") if isinstance(value, dict) else ""
            if not version_id.isdigit():
                raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
            external_id = f"{RELEASE_EXTERNAL_PREFIX}{version_id}"
            version = release_version(value.get("name"), self._config.version_name_prefixes)
            if version is None:
                skipped.append((external_id, REASON_VERSION_NAME_UNRECOGNIZED))
                continue
            items.append(await self._release_item(project_key, product, version, version_id, value))
        if not is_last:
            next_token = f"{RELEASE_TOKEN_PREFIX}{project_index}:{offset + len(values)}"
        elif project_index + 1 < len(self._config.products):
            next_token = f"{RELEASE_TOKEN_PREFIX}{project_index + 1}:0"
        else:
            next_token = None
        return ReleasePage(tuple(items), tuple(skipped), next_token)

    async def _release_item(
        self, project_key: str, product: str, version: str, version_id: str, jira_version: dict
    ) -> SourceItem:
        jql = release_jql(project_key, version_id, self._jql_filter)
        issues, complete = await search_release_issues(
            self._reader, jql, fields=RELEASE_ISSUE_FIELDS, bound=MAX_RELEASE_ISSUES, project_key=project_key
        )
        readable = [(key, fields) for key, fields in issues if fields.get("security") is None]
        text = render_release(
            base_url=self._reader.base_url,
            project_key=project_key,
            product=product,
            version=version,
            jira_version=jira_version,
            issues=readable,
            sections=self._config.sections,
            truncated_at=None if complete else MAX_RELEASE_ISSUES,
        )
        data = text.encode("utf-8")
        external_id = f"{RELEASE_EXTERNAL_PREFIX}{version_id}"
        self._rendered[external_id] = data
        return SourceItem(
            external_id=external_id,
            title=f"Release {version}",
            source_url=version_url(self._reader.base_url, project_key, version_id),
            version_marker=hashlib.sha256(data).hexdigest(),
            acl=AclFacet.scope(),
            products=(product,),
            version=version,
            role=RELEASE_DOCUMENT_ROLE,
        )

    def fetch(self, item: SourceItem) -> ItemContent:
        data = self._rendered.get(item.external_id)
        if data is None:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        return ItemContent(data=data, media_type="text/markdown")


__all__ = [
    "MAX_RELEASE_ISSUES",
    "RELEASE_DOCUMENT_ROLE",
    "JiraReleaseLister",
    "ReleasePage",
    "release_jql",
    "reader_is_cloud",
    "search_issue_page",
    "search_release_issues",
    "version_url",
]
