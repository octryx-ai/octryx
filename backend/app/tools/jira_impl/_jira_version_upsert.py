"""``create_jira_version``: create the version, or update the project's version of that name."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import _jira_helpers_api
from ._jira_helpers_api import _jira_fetch_project_versions


@dataclass(frozen=True)
class VersionRequest:
    """The version as asked; ``start_date`` is the raw parameter (only a truthy one is sent)."""

    project_key: str
    name: str
    description: str
    release_date: str
    start_date: Any


def _create_payload(request: VersionRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {"project": request.project_key, "name": request.name}
    if request.description:
        payload["description"] = request.description
    if request.release_date:
        payload["releaseDate"] = request.release_date
    if request.start_date:
        payload["startDate"] = str(request.start_date)
    return payload


def _update_payload(request: VersionRequest, existing: dict[str, Any]) -> dict[str, Any]:
    """Only the asked values that differ from the existing version."""
    update_payload: dict[str, Any] = {}
    if request.description and str(existing.get("description") or "").strip() != request.description:
        update_payload["description"] = request.description
    if request.release_date and str(existing.get("releaseDate") or "").strip() != request.release_date:
        update_payload["releaseDate"] = request.release_date
    if request.start_date and str(existing.get("startDate") or "").strip() != str(request.start_date).strip():
        update_payload["startDate"] = str(request.start_date).strip()
    return update_payload


async def _update_existing(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: VersionRequest,
    existing: dict[str, Any],
    api_version: str,
) -> dict[str, Any]:
    update_payload = _update_payload(request, existing)
    status_code = 200
    status = "existing"
    if update_payload and str(existing.get("id") or "").strip():
        status_code = await _jira_helpers_api._jira_api_put(
            client,
            jira_url,
            f"/version/{existing.get('id')}",
            headers=headers,
            payload=update_payload,
        )
        status = "updated"
    return {
        "version_id": existing.get("id"),
        "name": existing.get("name"),
        "project_key": request.project_key,
        "api_version": api_version,
        "release_date": request.release_date or str(existing.get("releaseDate") or "").strip(),
        "status_code": status_code,
        "status": status,
    }


async def upsert_version(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], request: VersionRequest
) -> dict[str, Any]:
    existing_versions, api_version = await _jira_fetch_project_versions(
        client,
        jira_url,
        headers=headers,
        project_key=request.project_key,
    )
    existing = next(
        (item for item in existing_versions if str(item.get("name") or "").strip().lower() == request.name.lower()),
        None,
    )
    if existing:
        return await _update_existing(
            client, jira_url, headers=headers, request=request, existing=existing, api_version=api_version
        )
    body, api_version, status_code = await _jira_helpers_api._jira_api_post(
        client, jira_url, "/version", headers=headers, payload=_create_payload(request)
    )
    result = body or {}
    return {
        "version_id": result.get("id"),
        "name": result.get("name"),
        "project_key": request.project_key,
        "api_version": api_version,
        "release_date": request.release_date,
        "status_code": status_code,
        "status": "created",
    }


__all__ = ["VersionRequest", "upsert_version"]
