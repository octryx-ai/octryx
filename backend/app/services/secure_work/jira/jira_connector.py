from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.connector_auth.atlassian_modes import JIRA
from app.services.outbound_egress import CONNECTION_JIRA, egress_transport

from ....models import WorkItemSyncConfig
from ....tools.jira_impl._jira_api_versions import api_versions, remember_api_version
from ....tools.jira_impl._jira_cloud import is_jira_cloud, jira_search
from ....tools.jira_impl._jira_errors import jql_error_message
from ...connector_auth.atlassian import auth_headers, request_auth
from ..intake.connections import intake_connection_config
from ..jira_values import object_value, optional_int, string_list

JIRA_SYNC_DEFAULT_LIMIT = 500
JIRA_SYNC_MAX_LIMIT = 5000

JIRA_SEARCH_FIELDS = ",".join(
    [
        "summary",
        "description",
        "project",
        "status",
        "assignee",
        "reporter",
        "creator",
        "priority",
        "issuetype",
        "created",
        "updated",
        "labels",
        "components",
        "fixVersions",
        "sprint",
        "board",
        "team",
        "parent",
        "issuelinks",
        "watcher",
        # The issue's comments, shown read-only on the item.
        "comment",
    ]
)


async def fetch_jira_issues_for_sync(
    db: AsyncSession,
    *,
    config: WorkItemSyncConfig,
    jql: str,
    limit: int | None,
) -> dict[str, Any]:
    project_config = await _resolve_jira_connector_config(db, config)
    connector = str(config.connection_id or "default")
    if project_config is None:
        return {
            "configured": False,
            "issues": [],
            "source_count": 0,
            "source_complete": True,
            "metadata": {"connector": connector,
                         "reason": "The intake's connection is no longer available in this Workspace."},
        }
    jira_url = str(project_config.get("jira_url") or "").strip().rstrip("/")
    auth_headers = _jira_auth_headers(project_config)
    http_auth = request_auth(JIRA, project_config)  # client credentials: no static header
    if not jira_url or not (auth_headers or http_auth):
        return {
            "configured": False,
            "issues": [],
            "source_count": 0,
            "source_complete": True,
            "metadata": {
                "connector": connector,
                "reason": "Jira connector is not configured with URL and credentials.",
            },
        }

    requested = _requested_limit(config, limit)
    issues: list[dict[str, Any]] = []
    total: int | None = None
    # Jira Cloud: POST /rest/api/3/search/jql paged by nextPageToken (no total, ``isLast`` ends it);
    # Server/DC: /search paged by startAt, with strict JQL validation.
    cloud = is_jira_cloud(jira_url, project_config)
    async with httpx.AsyncClient(
        timeout=30, follow_redirects=True, transport=egress_transport(CONNECTION_JIRA), auth=http_auth
    ) as client:
        start_at = 0
        page_token: str | None = None
        while True:
            try:
                found = await jira_search(
                    client,
                    jira_url,
                    headers={"Accept": "application/json", **auth_headers},
                    cloud=cloud,
                    jql=jql,
                    fields=_jira_search_fields(config),
                    max_results=min(100, requested - len(issues)),
                    start_at=start_at,
                    page_token=page_token,
                    # Strict validation: a broken JQL (typo in a custom filter) fails with Jira's own error
                    # messages instead of an opaque 400 (Server/DC parameter).
                    server_params={"validateQuery": "strict"},
                    api_get=_jira_api_get,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    # Coded, with Jira's own message (an invalid or, on Cloud, unbounded JQL).
                    detail = {"code": "jql_invalid", "message": _jql_error_detail(jql, exc.response)}
                    raise HTTPException(status_code=422, detail=detail) from exc
                raise
            page_issues = found.issues
            total = found.total
            issues.extend(_with_browse_urls(jira_url, page_issues))
            cloud_done = cloud and (found.is_last or found.next_page_token is None)
            if (
                not page_issues
                or len(issues) >= requested
                or (total is not None and len(issues) >= total)
                or cloud_done
            ):
                # Complete only when the source says so: an unknown total is complete only on an empty page
                # (a fall-out-of-filter conclusion depends on it, see ``jira_item_upsert.fall_out_check``).
                server_done = len(issues) >= total if total is not None else not page_issues
                complete = found.is_last if cloud else server_done
                return {
                    "configured": True,
                    "issues": issues,
                    "source_count": total if total is not None else len(issues),
                    "source_complete": complete,
                    "metadata": {
                        "api_version": found.api_version,
                        "connector": connector,
                        "jira_url": jira_url,
                        "requested_limit": requested,
                        "returned": len(issues),
                    },
                }
            start_at += len(page_issues)
            page_token = found.next_page_token


def _jql_error_detail(jql: str, response: httpx.Response) -> str:
    return f"Invalid JQL '{jql}': {jql_error_message(response)}"


def _requested_limit(config: WorkItemSyncConfig, limit: int | None) -> int:
    if limit is not None:
        return max(1, min(limit, JIRA_SYNC_MAX_LIMIT))
    sync_options = config.sync_options_json if isinstance(config.sync_options_json, dict) else {}
    configured_limit = optional_int(
        sync_options.get("max_results")
        or sync_options.get("manual_limit")
        or sync_options.get("issue_limit")
    )
    requested = configured_limit if configured_limit is not None else JIRA_SYNC_DEFAULT_LIMIT
    return max(1, min(requested, JIRA_SYNC_MAX_LIMIT))


def _jira_search_fields(config: WorkItemSyncConfig) -> str:
    fields = {field.strip() for field in JIRA_SEARCH_FIELDS.split(",") if field.strip()}
    mapping = object_value(config.field_mapping_json)
    options = object_value(config.sync_options_json)
    for key in ("sprint_field", "board_field", "team_field"):
        value = str(mapping.get(key) or options.get(key) or "").strip()
        if value:
            fields.add(value)
    fields.update(string_list(mapping.get("extra_fields") or options.get("extra_fields")))
    return ",".join(sorted(fields))


async def _resolve_jira_connector_config(db: AsyncSession, config: WorkItemSyncConfig) -> dict[str, Any] | None:
    return await intake_connection_config(db, config, "jira")


def _jira_auth_headers(config: dict[str, Any]) -> dict[str, str]:
    return auth_headers(JIRA, config)


async def _jira_api_get(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    last_error: httpx.Response | None = None
    # The version this instance answered last time first (Data Center: v2), so a run is not doubled by 404s.
    for api_version in api_versions(jira_url):
        response = await client.get(
            f"{jira_url}/rest/api/{api_version}{path}",
            headers=headers,
            params=params,
        )
        if response.status_code == 404:
            last_error = response
            continue
        response.raise_for_status()
        remember_api_version(jira_url, api_version)
        return response.json(), api_version
    if last_error is not None:
        last_error.raise_for_status()
    raise RuntimeError("Jira API endpoint not found")


def _with_browse_urls(jira_url: str, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for issue in issues:
        key = str(issue.get("key") or "").strip()
        if key and not issue.get("browse_url") and not issue.get("url"):
            issue = {**issue, "browse_url": f"{jira_url}/browse/{key}"}
        normalized.append(issue)
    return normalized
