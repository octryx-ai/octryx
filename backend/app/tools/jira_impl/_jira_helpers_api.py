"""Jira helper functions for HTTP transport helpers."""

import re
from datetime import datetime
from typing import Any

import httpx

from ._jira_api_versions import api_versions, remember_api_version


async def _jira_api_get(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    last_error = None
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


async def _jira_api_post(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, str, int]:
    last_error = None
    for api_version in api_versions(jira_url):
        response = await client.post(
            f"{jira_url}/rest/api/{api_version}{path}",
            headers=headers,
            json=payload,
        )
        if response.status_code == 404:
            last_error = response
            continue
        response.raise_for_status()
        remember_api_version(jira_url, api_version)
        body = response.json() if response.content else None
        return body, api_version, response.status_code

    if last_error is not None:
        last_error.raise_for_status()
    raise RuntimeError("Jira API endpoint not found")


async def _jira_api_put(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> int:
    last_error = None
    for api_version in api_versions(jira_url):
        response = await client.put(
            f"{jira_url}/rest/api/{api_version}{path}",
            headers=headers,
            json=payload,
        )
        if response.status_code in {404, 405}:
            last_error = response
            continue
        response.raise_for_status()
        remember_api_version(jira_url, api_version)
        return response.status_code

    if last_error is not None:
        last_error.raise_for_status()
    raise RuntimeError("Jira API endpoint not found")


async def _jira_agile_get(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.get(
        f"{jira_url}/rest/agile/1.0{path}",
        headers=headers,
        params=params,
    )
    response.raise_for_status()
    return response.json()


async def _jira_agile_post(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    response = await client.post(
        f"{jira_url}/rest/agile/1.0{path}",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    body = response.json() if response.content else None
    return body, response.status_code


async def _jira_agile_put(
    client: httpx.AsyncClient,
    jira_url: str,
    path: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, int]:
    response = await client.put(
        f"{jira_url}/rest/agile/1.0{path}",
        headers=headers,
        json=payload,
    )
    response.raise_for_status()
    body = response.json() if response.content else None
    return body, response.status_code


async def _jira_fetch_project_metadata(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
) -> tuple[dict[str, Any], str]:
    payload, api_version = await _jira_api_get(
        client,
        jira_url,
        f"/project/{project_key}",
        headers=headers,
    )
    return (payload if isinstance(payload, dict) else {}), api_version


async def _jira_fetch_project_versions(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    project_key: str,
) -> tuple[list[dict[str, Any]], str]:
    payload, api_version = await _jira_api_get(
        client,
        jira_url,
        f"/project/{project_key}/versions",
        headers=headers,
    )
    return (payload if isinstance(payload, list) else []), api_version


def _normalize_jira_sprint_datetime(raw_value: str, *, end_of_day: bool = False) -> str:
    candidate = str(raw_value or "").strip()
    if not candidate:
        return ""
    if "T" in candidate:
        return candidate
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return candidate
    local_now = datetime.now().astimezone()
    offset = local_now.strftime("%z")
    offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    hour = 17 if end_of_day else 9
    return f"{parsed.date().isoformat()}T{hour:02d}:00:00.000{offset}"


def _jira_user_matches_query(user: dict[str, Any], query: str) -> bool:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return True
    tokens = [token for token in re.split(r"\s+", normalized_query) if token]
    haystack = " ".join(
        str(user.get(key) or "").lower()
        for key in ("name", "key", "accountId", "displayName", "emailAddress")
    )
    if normalized_query in haystack:
        return True
    return bool(tokens) and all(token in haystack for token in tokens)


def _user_search_endpoints(
    normalized_query: str, *, project_key: str | None, limit: int, cloud: bool
) -> list[tuple[str, dict[str, Any]]]:
    """User search requests in the order they are tried; the first one that finds someone wins."""
    endpoints: list[tuple[str, dict[str, Any]]] = []
    if cloud:
        # Jira Cloud: people are found by ``query`` and identified by ``accountId``; ``username`` does not exist.
        if project_key and normalized_query:
            endpoints.append(
                ("/rest/api/3/user/assignable/search", {"project": project_key, "query": normalized_query, "maxResults": limit})
            )
        if normalized_query:
            endpoints.append(("/rest/api/3/user/search", {"query": normalized_query, "maxResults": limit}))
        if project_key:
            endpoints.append(("/rest/api/3/user/assignable/search", {"project": project_key, "maxResults": max(limit, 100)}))
    elif project_key and normalized_query:
        endpoints.append(
            (
                "/rest/api/2/user/assignable/search",
                {"project": project_key, "username": normalized_query, "maxResults": limit},
            )
        )
        endpoints.append(
            (
                "/rest/api/2/user/assignable/search",
                {"project": project_key, "query": normalized_query, "maxResults": limit},
            )
        )
    if normalized_query and not cloud:
        endpoints.append(("/rest/api/2/user/search", {"username": normalized_query, "maxResults": limit}))
        endpoints.append(("/rest/api/2/user/search", {"query": normalized_query, "maxResults": limit}))
    if project_key and not cloud:
        endpoints.append(("/rest/api/2/user/assignable/search", {"project": project_key, "maxResults": max(limit, 100)}))
    return endpoints


async def _jira_search_users_raw(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    query: str,
    project_key: str | None,
    limit: int,
    cloud: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    normalized_query = str(query or "").strip()

    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    endpoints = _user_search_endpoints(normalized_query, project_key=project_key, limit=limit, cloud=cloud)
    for path, params in endpoints:
        response = await client.get(f"{jira_url}{path}", headers=headers, params=params)
        if response.status_code >= 400:
            continue
        payload = response.json() if response.content else []
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not _jira_user_matches_query(item, normalized_query):
                continue
            identity = item.get("accountId") if cloud else (item.get("name") or item.get("key") or item.get("accountId"))
            dedupe_key = str(identity or "").strip().lower()
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            results.append(item)
        if results:
            break

    return results[:limit], "3" if cloud else "2"
