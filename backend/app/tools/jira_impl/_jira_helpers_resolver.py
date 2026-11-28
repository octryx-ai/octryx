"""Jira helper functions for resolving user-facing names to Jira IDs/names."""

from typing import Any

from . import _jira_helpers_api

# The issue type a create without one asks for (the tool schema says "default: Task"); the project's own types then
# decide what Jira gets (``_jira_resolve_issue_type_name``: Task, else Improvement, Story ...).
DEFAULT_JIRA_ISSUE_TYPE = "Task"


def _jira_normalize_user_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name"),
        "key": item.get("key"),
        "account_id": item.get("accountId"),
        "display_name": item.get("displayName"),
        "email": item.get("emailAddress"),
        "active": bool(item.get("active", True)),
    }


async def _jira_resolve_assignee_name(
    client,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
    desired_assignee: str,
) -> str:
    candidate = str(desired_assignee or "").strip()
    if not candidate:
        return ""

    users, _ = await _jira_helpers_api._jira_search_users_raw(
        client,
        jira_url,
        headers=headers,
        query=candidate,
        project_key=project_key,
        limit=20,
    )
    if not users:
        return candidate

    needle = candidate.casefold()
    for field in ("name", "displayName", "emailAddress", "key", "accountId"):
        for user in users:
            value = str(user.get(field) or "").strip()
            if value and value.casefold() == needle:
                return str(user.get("name") or candidate).strip()

    startswith_name = [user for user in users if str(user.get("name") or "").strip().casefold().startswith(needle)]
    if len(startswith_name) == 1:
        return str(startswith_name[0].get("name") or candidate).strip()

    startswith_display = [
        user for user in users if str(user.get("displayName") or "").strip().casefold().startswith(needle)
    ]
    if len(startswith_display) == 1:
        return str(startswith_display[0].get("name") or candidate).strip()

    if len(users) == 1:
        return str(users[0].get("name") or candidate).strip()
    return candidate


async def _jira_resolve_cloud_assignee(
    client,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
    desired_assignee: str,
) -> str | None:
    candidate = str(desired_assignee or "").strip()
    if not candidate:
        return None
    users, _ = await _jira_helpers_api._jira_search_users_raw(
        client, jira_url, headers=headers, query=candidate, project_key=project_key, limit=20, cloud=True
    )
    users = [user for user in users if str(user.get("accountId") or "").strip()]
    needle = candidate.casefold()
    for field in ("accountId", "displayName", "emailAddress"):
        exact = [user for user in users if str(user.get(field) or "").strip().casefold() == needle]
        if len(exact) == 1:
            return str(exact[0]["accountId"]).strip()
    return None


async def _jira_resolve_priority_name(
    client,
    jira_url: str,
    *,
    headers: dict[str, str],
    desired_name: str,
) -> str:
    candidate = str(desired_name or "").strip()
    if not candidate:
        return ""

    alias_map = {
        "highest": "Blocker",
        "blocker": "Blocker",
        "critical": "Critical",
        "urgent": "Critical",
        "high": "Major",
        "major": "Major",
        "medium": "Minor",
        "normal": "Minor",
        "minor": "Minor",
        "low": "Trivial",
        "lowest": "Trivial",
        "trivial": "Trivial",
    }
    payload, _ = await _jira_helpers_api._jira_api_get(client, jira_url, "/priority", headers=headers)
    priorities = payload if isinstance(payload, list) else []
    by_name = {
        str(item.get("name") or "").strip().casefold(): str(item.get("name") or "").strip()
        for item in priorities
        if str(item.get("name") or "").strip()
    }
    if candidate.casefold() in by_name:
        return by_name[candidate.casefold()]
    mapped = alias_map.get(candidate.casefold())
    if mapped and mapped.casefold() in by_name:
        return by_name[mapped.casefold()]
    return candidate


async def _jira_resolve_fix_version_refs(
    client,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
    fix_versions: list[Any],
) -> list[dict[str, str]]:
    from ._jira_helpers_api import _jira_fetch_project_versions

    requested = [str(item).strip() for item in (fix_versions or []) if str(item).strip()]
    if not requested:
        return []

    versions, _ = await _jira_fetch_project_versions(
        client,
        jira_url,
        headers=headers,
        project_key=project_key,
    )
    by_name = {str(item.get("name") or "").strip().casefold(): item for item in versions}
    by_id = {str(item.get("id") or "").strip(): item for item in versions}
    resolved: list[dict[str, str]] = []
    for value in requested:
        match = by_id.get(value) or by_name.get(value.casefold())
        if match:
            resolved.append({"id": str(match.get("id") or "").strip()})
        else:
            resolved.append({"name": value})
    return resolved


async def _jira_resolve_issue_type_name(
    client,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
    desired_name: str,
) -> str:
    project_payload, _ = await _jira_helpers_api._jira_api_get(
        client,
        jira_url,
        f"/project/{project_key}",
        headers=headers,
    )
    issue_types = project_payload.get("issueTypes") or []
    normalized_map = {
        str(item.get("name") or "").strip().lower(): str(item.get("name") or "").strip()
        for item in issue_types
        if str(item.get("name") or "").strip()
    }
    desired = str(desired_name or "").strip()
    desired_lower = desired.lower()
    if desired_lower in normalized_map:
        return normalized_map[desired_lower]

    alias_preferences = {
        "task": ["improvement", "story", "bug", "initiative", "epic"],
        "technical task": ["improvement", "story", "bug", "initiative", "epic"],
    }
    for alias in alias_preferences.get(desired_lower, []):
        if alias in normalized_map:
            return normalized_map[alias]

    for item in issue_types:
        if not bool(item.get("subtask")) and str(item.get("name") or "").strip():
            return str(item.get("name") or "").strip()

    return desired or DEFAULT_JIRA_ISSUE_TYPE
