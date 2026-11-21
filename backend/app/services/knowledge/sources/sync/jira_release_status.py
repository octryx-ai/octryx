"""The live status of one release, read from Jira now, never from stored knowledge.

"What is the status of 2.4.20" changes by the hour, so it is not answered from the release-notes
sources (``jira_releases.py``) but queried live, through the same governed connection and the same
explicit configuration:

1. **Product mapping.** The Workspace's Jira connector whose release configuration maps a project to
   the product (``releases.products``). None is ``needs_configuration``
   (``release_product_not_configured``); two are ``needs_configuration``
   (``release_product_ambiguous``): the product never resolves by guessing.
2. **Connection.** The Workspace's own Jira tool connection, and the project must lie inside its
   allowlist (``scope_not_allowed``), exactly as for the sync.
3. **Version.** The project's versions, matched by their normalized name
   (``jira_release_config.release_version``, with the configured prefixes). No match is
   ``not_found``.
4. **Issues.** The version's fixVersion issues (with the connector's JQL filter), bounded: counts
   per status category, and the open issues whose priority is a configured blocker priority.
   Issues with an issue security level are not counted and never listed, as in the sync.

Only ``GET`` is used (``http.SourceReader``): this can never write to Jira. Every failure is a
fixed state and reason; no response body, URL of a failed call, or credential is returned.
"""

from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .....models.project.knowledge_source_sync import CONNECTOR_KIND_JIRA, KnowledgeSourceConnector
from .....time_utils import utc_now
from .contract import (
    REASON_SCOPE_NOT_ALLOWED,
    REASON_SOURCE_CONTRACT_VIOLATION,
    REASON_SOURCE_NOT_FOUND,
    REASON_SOURCE_UNAUTHORIZED,
    ConnectorError,
)
from .http import SourceReader
from .jira_release_config import (
    REASON_RELEASE_PRODUCT_NOT_CONFIGURED,
    ReleaseConfig,
    load_release_config,
    release_version,
)
from .jira_releases import release_jql, search_release_issues, version_url
from .scope_connections import resolve_scope_connections, scope_allowed

STATE_OK = "ok"
STATE_NEEDS_CONFIGURATION = "needs_configuration"
STATE_NOT_FOUND = "not_found"
STATE_DENIED = "denied"
STATE_UNAVAILABLE = "unavailable"
STATE_INVALID_REQUEST = "invalid_request"
REASON_RELEASE_PRODUCT_AMBIGUOUS = "release_product_ambiguous"
REASON_VERSION_NOT_FOUND = "version_not_found"

MAX_CONNECTORS = 50
VERSION_PAGE_SIZE = 50
MAX_VERSION_PAGES = 20
MAX_STATUS_ISSUES = 1000
MAX_BLOCKERS = 20
STATUS_FIELDS = "summary,status,priority,issuetype,security"
_CATEGORY = {"new": "to_do", "indeterminate": "in_progress", "done": "done"}


# The release's progress as one closed value, so no reader infers "complete" from a mixed state.
WORK_STATE_NO_ISSUES = "no_issues"
WORK_STATE_ALL_DONE = "all_done"
WORK_STATE_OPEN_WORK = "open_work"
WORK_STATE_LISTING_TRUNCATED = "listing_truncated"


def _work_state(counts: dict[str, int], *, listing_complete: bool) -> str:
    open_count = counts["to_do"] + counts["in_progress"] + counts["unknown"]
    if open_count:
        return WORK_STATE_OPEN_WORK
    if not listing_complete:
        # Every listed issue is done, but the bound cut the listing: the rest is not known.
        return WORK_STATE_LISTING_TRUNCATED
    return WORK_STATE_ALL_DONE if counts["done"] else WORK_STATE_NO_ISSUES


def _state(state: str, reason: str | None = None, **extra: object) -> dict[str, object]:
    return {"state": state, "reason": reason, **extra}


def _failure(error: ConnectorError) -> dict[str, object]:
    if error.reason == REASON_SOURCE_UNAUTHORIZED:
        return _state(STATE_DENIED, error.reason)
    if error.reason == REASON_SOURCE_NOT_FOUND:
        return _state(STATE_NOT_FOUND, error.reason)
    return _state(STATE_UNAVAILABLE, error.reason)


async def _mapping(
    db: AsyncSession, project_id: str, product: str
) -> list[tuple[KnowledgeSourceConnector, ReleaseConfig, str]]:
    rows = (
        (
            await db.execute(
                select(KnowledgeSourceConnector)
                .where(
                    KnowledgeSourceConnector.project_id == project_id,
                    KnowledgeSourceConnector.kind == CONNECTOR_KIND_JIRA,
                )
                .order_by(KnowledgeSourceConnector.connector_key)
                .limit(MAX_CONNECTORS)
            )
        )
        .scalars()
        .all()
    )
    matches = []
    for row in rows:
        config = load_release_config(dict(row.scope or {}))
        for project_key, mapped in config.products if config else ():
            if mapped == product:
                matches.append((row, config, project_key))
    return matches


async def _find_version(reader: SourceReader, project_key: str, version: str, prefixes: tuple[str, ...]):
    offset = 0
    for _ in range(MAX_VERSION_PAGES):
        payload = await reader.get_json(
            f"/rest/api/2/project/{project_key}/version",
            {"startAt": offset, "maxResults": VERSION_PAGE_SIZE, "orderBy": "sequence"},
        )
        values, is_last = payload.get("values"), payload.get("isLast")
        if not isinstance(values, list) or type(is_last) is not bool:
            raise ConnectorError(REASON_SOURCE_CONTRACT_VIOLATION)
        for value in values:
            if isinstance(value, dict) and release_version(value.get("name"), prefixes) == version:
                return value
        if is_last or not values:
            return None
        offset += len(values)
    return None


def _field_name(fields: dict, key: str) -> str:
    value = fields.get(key)
    return str(value.get("name") or "") if isinstance(value, dict) else ""


async def jira_release_status(
    db: AsyncSession, *, project_id: str, product: object, version: object, transport=None
) -> dict[str, object]:
    """The live status of ``product`` ``version`` in the Workspace's Jira. ``transport`` is for tests."""
    if type(product) is not str or not product.strip():
        return _state(STATE_INVALID_REQUEST)
    product_key = product.strip().lower()
    matches = await _mapping(db, project_id, product_key)
    if not matches:
        return _state(STATE_NEEDS_CONFIGURATION, REASON_RELEASE_PRODUCT_NOT_CONFIGURED, product=product_key)
    if len(matches) > 1:
        return _state(STATE_NEEDS_CONFIGURATION, REASON_RELEASE_PRODUCT_AMBIGUOUS, product=product_key)
    row, config, project_key = matches[0]
    # Read like a Jira name: "2.4.20", "v2.4.20", or "Release 2.4.20" with that prefix configured.
    wanted = release_version(version, config.version_name_prefixes)
    if wanted is None:
        return _state(STATE_INVALID_REQUEST, product=product_key)
    project_scope = {"project_keys": [project_key]}
    try:
        # The project's own connection when a named connection binds it.
        scoped = await resolve_scope_connections(
            db, kind=CONNECTOR_KIND_JIRA, project_id=project_id, scope=project_scope,
            connection_id=row.connection_id,
        )
    except ConnectorError as error:
        return _state(STATE_NEEDS_CONFIGURATION, error.reason, product=product_key)
    scope = dict(row.scope or {})
    connection = scoped.single
    if connection is None or not scope_allowed(CONNECTOR_KIND_JIRA, project_scope, scoped):
        return _state(STATE_NEEDS_CONFIGURATION, REASON_SCOPE_NOT_ALLOWED, product=product_key)
    reader = SourceReader(connection, transport=transport)
    try:
        jira_version = await _find_version(reader, project_key, wanted, config.version_name_prefixes)
        if jira_version is None or not str(jira_version.get("id") or "").isdigit():
            return _state(STATE_NOT_FOUND, REASON_VERSION_NOT_FOUND, product=product_key, version=wanted)
        jql = release_jql(project_key, str(jira_version["id"]), scope.get("jql"))
        issues, listing_complete = await search_release_issues(
            reader, jql, fields=STATUS_FIELDS, bound=MAX_STATUS_ISSUES, project_key=project_key
        )
    except ConnectorError as error:
        return {**_failure(error), "product": product_key, "version": wanted}
    return _status(reader.base_url, config, project_key, product_key, wanted, jira_version, jql, issues,
                   listing_complete)


def _status(
    base: str, config: ReleaseConfig, project_key: str, product_key: str, wanted: str, jira_version: dict,
    jql: str, issues: list, listing_complete: bool,
) -> dict[str, object]:
    """The ``ok`` answer: counts per status category and the open blockers of the readable issues."""
    readable = [(key, fields) for key, fields in issues if fields.get("security") is None]
    counts, blockers = _tally(readable, config, base)
    return _state(
        STATE_OK,
        product=product_key,
        version=wanted,
        jira_project=project_key,
        jira_version=str(jira_version.get("name") or ""),
        released=jira_version.get("released") is True,
        release_date=jira_version.get("releaseDate"),
        archived=jira_version.get("archived") is True,
        version_url=version_url(base, project_key, str(jira_version["id"])),
        issues_url=f"{base}/issues/?jql={quote(jql)}",
        issue_count=len(readable),
        status_counts=counts,
        open_issue_count=counts["to_do"] + counts["in_progress"] + counts["unknown"],
        # False when the issue bound cut the listing (counts are a lower
        # bound); it says nothing about the release's progress, which ``work_state`` states.
        issue_listing_complete=listing_complete,
        work_state=_work_state(counts, listing_complete=listing_complete),
        blocker_priorities=list(config.blocker_priorities),
        open_blockers=blockers if config.blocker_priorities else None,
        queried_at=utc_now().isoformat(),
    )


def _tally(
    readable: list, config: ReleaseConfig, base: str
) -> tuple[dict[str, int], list[dict[str, str]]]:
    counts = {"to_do": 0, "in_progress": 0, "done": 0, "unknown": 0}
    blockers: list[dict[str, str]] = []
    wanted_priorities = {name.casefold() for name in config.blocker_priorities}
    for key, fields in readable:
        status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
        category = status.get("statusCategory") if isinstance(status.get("statusCategory"), dict) else {}
        bucket = _CATEGORY.get(str(category.get("key") or ""), "unknown")
        counts[bucket] += 1
        priority = _field_name(fields, "priority")
        if bucket != "done" and priority.casefold() in wanted_priorities and len(blockers) < MAX_BLOCKERS:
            blockers.append(
                {
                    "key": key,
                    "summary": " ".join(str(fields.get("summary") or "").split())[:200],
                    "priority": priority,
                    "status": str(status.get("name") or ""),
                    "url": f"{base}/browse/{key}",
                }
            )
    return counts, blockers

__all__ = ["jira_release_status"]
