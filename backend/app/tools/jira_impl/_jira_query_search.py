"""Jira search helper tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from ..empty_search_hint import with_empty_search_hint
from . import _jira_helpers_api
from ._jira_allowlist import ISSUE_KEY, allowed_issues
from ._jira_cloud import is_jira_cloud, jira_search
from ._jira_errors import CODE_JQL_INVALID, jql_error_message
from ._jira_evidence import with_issue_source
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_default_project_key,
    _jira_http,
)
from ._jira_helpers_jql import (
    _inject_project_restriction,
    _looks_like_jql_query,
    _normalize_jql_shorthand,
    _split_order_by_clause,
)
from ._jira_helpers_resolver import _jira_normalize_user_summary
from ._jira_helpers_ticket import _effective_search_limit, _ticket_summary
from ._jira_jql_confine import jql_problem
from ._jira_user_email import account_by_id, accounts_by_email


class SearchJiraTickets:
    name = "search_jira_tickets"
    description = "Search Jira tickets by free text, key or JQL."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        allowed_projects = _jira_allowed_projects(context)

        query = str(params.get("query") or "").strip()
        jql = str(params.get("jql") or "").strip()
        project_key = str(params.get("project_key") or "").strip()
        fix_versions = _normalize_fix_versions(params)
        limit = _effective_search_limit(params, context)
        start_at = max(0, int(params.get("start_at") or 0))

        # Treat wildcard-only queries as empty (model often sends "*" or "all")
        if query in ("*", "all", "any", "everything"):
            query = ""

        error, jql = _search_jql(query, jql, project_key, fix_versions, allowed_projects)
        if error:
            return error
        error, jql = _confined_jql(jql, allowed_projects)
        if error:
            return error
        error, found = await _run_search(context, jira_url, jql, limit=limit, start_at=start_at)
        if error:
            return error

        # C-1b: whatever came back, only issues of allowed projects leave this tool; no count of the others.
        issues = allowed_issues(found.issues, allowed_projects)[:limit]
        return with_empty_search_hint({
            "query": query or None,
            "jql": jql,
            "api_version": found.api_version,
            "start_at": start_at,
            "max_results": limit,
            # r9 C-1d: Jira's total may count issues of other pages outside the allowlist; never shown then.
            "total": None if allowed_projects else found.total,
            # Each ticket names its /browse page on the configured Jira (evidence fields).
            "results": [with_issue_source(_ticket_summary(issue), jira_url) for issue in issues],
        })


def _project_clause(project_key: str, allowed_projects: list[str] | None) -> tuple[dict[str, Any] | None, list[str]]:
    jql_parts: list[str] = []
    if allowed_projects:
        if project_key:
            pk_upper = project_key.upper()
            if pk_upper not in allowed_projects:
                return {"error": f"Project '{project_key}' is not in the allowed list: {allowed_projects}"}, []
            jql_parts.append(f'project = "{pk_upper}"')
        else:
            keys_quoted = ", ".join(f'"{k}"' for k in allowed_projects)
            jql_parts.append(f"project in ({keys_quoted})")
    elif project_key:
        jql_parts.append(f'project = "{project_key}"')
    return None, jql_parts


def _search_jql(
    query: str, jql: str, project_key: str, fix_versions: list[str], allowed_projects: list[str] | None
) -> tuple[dict[str, Any] | None, str]:
    jql_has_fix_version_filter = False
    if not query and not jql:
        # No explicit query — build a default "recent tickets" JQL
        error, jql_parts = _project_clause(project_key, allowed_projects)
        if error:
            return error, ""
        if fix_versions:
            jql_parts.append(_fix_version_jql(fix_versions))
            jql_has_fix_version_filter = True
        jql = (" AND ".join(jql_parts) + " " if jql_parts else "") + "ORDER BY updated DESC"

    if not jql and _looks_like_jql_query(query):
        jql = _normalize_jql_shorthand(query)

    if not jql:
        # A JQL string literal escapes "\\" and '"'; a key must look like a key.
        escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
        # Enforce project allowlist: restrict to configured projects
        error, jql_parts = _project_clause(project_key, allowed_projects)
        if error:
            return error, ""

        if ISSUE_KEY.fullmatch(query.upper()):
            jql_parts.append(f'(key = "{query.upper()}" OR text ~ "\\"{escaped_query}\\"")')
        else:
            jql_parts.append(f'text ~ "\\"{escaped_query}\\""')
        if fix_versions:
            jql_parts.append(_fix_version_jql(fix_versions))
        jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"
    elif fix_versions and not jql_has_fix_version_filter:
        base_jql, order_by = _split_order_by_clause(_normalize_jql_shorthand(jql))
        parts = [f"({base_jql})"] if base_jql else []
        parts.append(_fix_version_jql(fix_versions))
        jql = " AND ".join(parts) + (f" {order_by}" if order_by else "")
    return None, jql


def _confined_jql(jql: str, allowed_projects: list[str] | None) -> tuple[dict[str, Any] | None, str]:
    problem = jql_problem(jql)
    if problem is not None:
        # An unterminated quote, a stray ")" or a bare backslash could break out.
        return {"error": "The JQL has unbalanced parentheses or quotes, or a backslash outside quotes.",
                "code": problem, "jql": jql}, jql
    if allowed_projects:
        # C-1b: every query, built or provided, goes through the confined project restriction.
        return None, _inject_project_restriction(jql, allowed_projects)
    return None, _normalize_jql_shorthand(jql)


async def _run_search(
    context: ToolContext, jira_url: str, jql: str, *, limit: int, start_at: int
) -> tuple[dict[str, Any] | None, Any]:
    headers = {"Accept": "application/json", **_jira_auth_headers(context)}
    async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
        # Cloud: POST /rest/api/3/search/jql with nextPageToken; Server/DC: /search with startAt.
        try:
            found = await jira_search(
                client,
                jira_url,
                headers=headers,
                cloud=is_jira_cloud(jira_url, context.project_config),
                jql=jql,
                # r9 C-1c: ``project`` lets the allowlist filter cross-check every returned key.
                fields="summary,status,assignee,reporter,creator,priority,issuetype,created,updated,project",
                max_results=limit,
                start_at=start_at,
                api_get=_jira_helpers_api._jira_api_get,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            # An invalid (or, on Cloud, unbounded) JQL answers with Jira's own message.
            message = jql_error_message(exc.response)
            return {"error": f"Jira rejected the query: {message}", "code": CODE_JQL_INVALID,
                    "message": message, "jql": jql}, None
    return None, found


def _normalize_fix_versions(params: dict) -> list[str]:
    values: list[object] = []
    for key in ("fix_version", "fixVersion"):
        value = params.get(key)
        if value:
            values.append(value)
    for key in ("fix_versions", "fixVersions"):
        value = params.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value:
            values.append(value)

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _fix_version_jql(fix_versions: list[str]) -> str:
    quoted = [_jql_quote(value) for value in fix_versions if str(value or "").strip()]
    if not quoted:
        return ""
    if len(quoted) == 1:
        return f"fixVersion = {quoted[0]}"
    return f"fixVersion in ({', '.join(quoted)})"


def _jql_quote(value: str) -> str:
    escaped = str(value).strip().replace('"', '\\"')
    return f'"{escaped}"'


async def _user_by_email(context: ToolContext, jira_url: str, email: str) -> dict[str, Any]:
    if not is_jira_cloud(jira_url, context.project_config):
        return {"error": "A lookup by email needs a Jira Cloud connection (Atlassian accounts)."}
    headers = {"Accept": "application/json", **_jira_auth_headers(context)}
    async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
        users = await accounts_by_email(client, jira_url, headers=headers, email=email)
    return {"email": email, "api_version": "3", "users": [_jira_normalize_user_summary(item) for item in users],
            "total": len(users)}


async def _user_by_account_id(context: ToolContext, jira_url: str, account_id: str) -> dict[str, Any]:
    if not is_jira_cloud(jira_url, context.project_config):
        return {"error": "A lookup by account id needs a Jira Cloud connection (Atlassian accounts)."}
    headers = {"Accept": "application/json", **_jira_auth_headers(context)}
    async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
        users = await account_by_id(client, jira_url, headers=headers, account_id=account_id)
    return {"account_id": account_id, "api_version": "3",
            "users": [_jira_normalize_user_summary(item) for item in users], "total": len(users)}


class SearchJiraUsers:
    name = "search_jira_users"
    description = "Search Jira users, preferably assignable in the configured project, to resolve valid assignees."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        query = str(params.get("query") or "").strip()
        email = str(params.get("email") or "").strip()
        if email:
            return await _user_by_email(context, jira_url, email)
        account_id = str(params.get("account_id") or "").strip()
        if account_id:
            return await _user_by_account_id(context, jira_url, account_id)

        project_key = str(params.get("project_key") or _jira_default_project_key(context) or "").strip().upper() or None
        allowed = _jira_allowed_projects(context)
        if project_key and allowed and project_key not in allowed:
            project_key = allowed[0] if len(allowed) == 1 else None
        if not query and not project_key:
            return {"error": "query or configured project key is required"}

        limit = max(1, min(int(params.get("limit") or 10), 50))
        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            users, api_version = await _jira_helpers_api._jira_search_users_raw(
                client,
                jira_url,
                headers=headers,
                query=query,
                project_key=project_key,
                limit=limit,
                # Only a Cloud connection passes the flag, so the Server/DC call is.
                **({"cloud": True} if is_jira_cloud(jira_url, context.project_config) else {}),
            )

        return {
            "project_key": project_key,
            "query": query,
            "api_version": api_version,
            "users": [_jira_normalize_user_summary(item) for item in users],
            "total": len(users),
        }
