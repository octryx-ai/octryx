"""The release side of ``create_jira_release_bundle``: request, assignee accounts, version, release."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import _jira_helpers_api
from ._jira_helpers_api import _jira_fetch_project_versions
from ._jira_helpers_resolver import _jira_resolve_cloud_assignee


@dataclass(frozen=True)
class BundleRequest:
    project_key: str
    release_name: str
    tickets: list[Any]
    existing_ticket_ids: list[str]
    issue_type_default: str
    release_now: bool
    release_date: str
    version_description: str
    allowed: list[str] | None
    cloud: bool


@dataclass(frozen=True)
class ReleaseVersion:
    version_id: str
    version_name: str
    created: bool
    existing: dict[str, Any] | None
    api_version: str

    def fix_versions(self) -> list[dict[str, str]]:
        return [{"id": self.version_id}] if self.version_id else [{"name": self.version_name}]


async def resolve_cloud_accounts(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], request: BundleRequest
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    cloud_accounts: dict[str, str] = {}
    for ticket in request.tickets:
        person = str(ticket.get("assignee") or "").strip() if isinstance(ticket, dict) else ""
        if not person or person in cloud_accounts:
            continue
        account_id = await _jira_resolve_cloud_assignee(
            client, jira_url, headers=headers, project_key=request.project_key, desired_assignee=person
        )
        if account_id is None:
            return {
                "error": (
                    f"The assignee '{person}' could not be resolved to exactly one Jira Cloud account; "
                    "nothing was created."
                )
            }, cloud_accounts
        cloud_accounts[person] = account_id
    return None, cloud_accounts


async def _update_existing_version(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: BundleRequest,
    existing: dict[str, Any],
    version_id: str,
) -> None:
    version_update_payload: dict[str, Any] = {}
    if request.version_description and str(existing.get("description") or "").strip() != request.version_description:
        version_update_payload["description"] = request.version_description
    if request.release_date and str(existing.get("releaseDate") or "").strip() != request.release_date:
        version_update_payload["releaseDate"] = request.release_date
    if version_update_payload:
        await _jira_helpers_api._jira_api_put(
            client,
            jira_url,
            f"/version/{version_id}",
            headers=headers,
            payload=version_update_payload,
        )


async def ensure_release_version(
    client: httpx.AsyncClient, jira_url: str, *, headers: dict[str, str], request: BundleRequest
) -> ReleaseVersion:
    versions, api_version = await _jira_fetch_project_versions(
        client,
        jira_url,
        headers=headers,
        project_key=request.project_key,
    )
    release_name = request.release_name
    existing_version = next(
        (item for item in versions if str(item.get("name") or "").strip().lower() == release_name.lower()),
        None,
    )
    existing = existing_version if isinstance(existing_version, dict) else None
    version_id = str(existing.get("id") or "") if existing is not None else ""
    if version_id:
        await _update_existing_version(
            client, jira_url, headers=headers, request=request, existing=existing, version_id=version_id
        )
        return ReleaseVersion(version_id, str(existing.get("name") or release_name), False, existing, api_version)
    version_payload: dict[str, Any] = {"project": request.project_key, "name": release_name}
    if request.version_description:
        version_payload["description"] = request.version_description
    if request.release_date:
        version_payload["releaseDate"] = request.release_date
    body, api_version, _ = await _jira_helpers_api._jira_api_post(
        client,
        jira_url,
        "/version",
        headers=headers,
        payload=version_payload,
    )
    version_result = body or {}
    return ReleaseVersion(
        str(version_result.get("id") or ""),
        str(version_result.get("name") or release_name),
        True,
        existing,
        api_version,
    )


async def release_version(
    client: httpx.AsyncClient,
    jira_url: str,
    *,
    headers: dict[str, str],
    request: BundleRequest,
    version: ReleaseVersion,
) -> int | None:
    if not (request.release_now and version.version_id):
        return None
    release_payload: dict[str, Any] = {"released": True}
    if request.release_date:
        release_payload["releaseDate"] = request.release_date
    return await _jira_helpers_api._jira_api_put(
        client,
        jira_url,
        f"/version/{version.version_id}",
        headers=headers,
        payload=release_payload,
    )


__all__ = ["BundleRequest", "ReleaseVersion", "ensure_release_version", "release_version", "resolve_cloud_accounts"]
