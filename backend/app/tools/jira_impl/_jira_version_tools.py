"""Jira version and release tool classes."""

from typing import Any

import httpx

from app.services.outbound_egress import CONNECTION_JIRA, egress_transport
from app.tools.context import ToolContext

from . import _jira_helpers_api
from ._jira_evidence import with_project_source, with_version_source
from ._jira_helpers_context import (
    _jira_allowed_projects,
    _jira_auth_headers,
    _jira_base_url,
    _jira_http,
    _normalize_requested_release_date,
)
from ._jira_helpers_ticket import _maybe_block_change_with_approval
from ._jira_version_upsert import VersionRequest, upsert_version


class ListJiraProjects:
    name = "list_jira_projects"
    description = "List Jira project keys available to this project connector."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        del params
        jira_url = _jira_base_url(context)
        allowed = _jira_allowed_projects(context)
        if allowed:
            return {
                "source": "project_config",
                "restricted": True,
                # Each project names its page on the configured Jira (evidence fields).
                "projects": [with_project_source({"key": key, "allowed": True}, jira_url) for key in allowed],
                "total": len(allowed),
            }
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            payload, api_version = await _jira_helpers_api._jira_api_get(
                client,
                jira_url,
                "/project/search",
                headers=headers,
                params={"maxResults": 100},
            )

        raw_projects = payload.get("values") if isinstance(payload, dict) else []
        projects = raw_projects if isinstance(raw_projects, list) else []
        return {
            "source": "jira",
            "restricted": False,
            "api_version": api_version,
            "projects": [
                with_project_source(
                    {
                        "key": str(project.get("key") or "").strip(),
                        "name": str(project.get("name") or "").strip(),
                        "id": str(project.get("id") or "").strip(),
                        "project_type_key": str(project.get("projectTypeKey") or "").strip(),
                    },
                    jira_url,
                )
                for project in projects
                if isinstance(project, dict) and str(project.get("key") or "").strip()
            ],
            "total": payload.get("total", len(projects)) if isinstance(payload, dict) else len(projects),
        }


class ListJiraVersions:
    name = "list_jira_versions"
    description = "List all versions (releases) for a Jira project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        error, project_keys = _version_project_keys(params, _jira_allowed_projects(context))
        if error:
            return error

        headers = {"Accept": "application/json", **_jira_auth_headers(context)}
        project_results: list[dict[str, Any]] = []
        flat_versions: list[dict[str, Any]] = []
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            api_version = ""
            for key in project_keys:
                data, api_version = await _jira_helpers_api._jira_api_get(
                    client,
                    jira_url,
                    f"/project/{key}/versions",
                    headers=headers,
                )
                summarized_versions = _summarized_versions(data, key, jira_url)
                project_results.append(
                    {
                        "project_key": key,
                        "version_count": len(summarized_versions),
                        "versions": summarized_versions,
                    }
                )
                flat_versions.extend(summarized_versions)

        return {
            "project_key": project_keys[0] if len(project_keys) == 1 else None,
            "project_keys": project_keys,
            "api_version": api_version,
            "projects": project_results,
            "versions": flat_versions,
        }


def _version_project_keys(params: dict, allowed: list[str] | None) -> tuple[dict[str, Any] | None, list[str]]:
    project_key = str(params.get("project_key") or "").strip().upper()
    if project_key:
        if allowed and project_key not in allowed:
            return {"error": f"Project '{project_key}' is not in the allowed list: {allowed}"}, []
        return None, [project_key]
    if allowed:
        return None, allowed
    return {
        "error": "project_key is required when Jira has no configured project allowlist",
        "next_action": "Call list_jira_projects first or configure jira_allowed_projects for this project.",
    }, []


def _summarized_versions(data: Any, key: str, jira_url: str) -> list[dict[str, Any]]:
    versions = data if isinstance(data, list) else []
    # Each version names its page on the configured Jira (evidence fields).
    return [
        with_version_source(
            {
                "id": v.get("id"),
                "name": v.get("name"),
                "description": v.get("description"),
                "released": v.get("released", False),
                "archived": v.get("archived", False),
                "release_date": v.get("releaseDate"),
                "start_date": v.get("startDate"),
                "project_key": key,
            },
            jira_url,
        )
        for v in versions
        if isinstance(v, dict)
    ]


class CreateJiraVersion:
    name = "create_jira_version"
    description = "Create a new version (release) in a Jira project."

    async def preview(self, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        project_key = str(params.get("project_key") or "").strip().upper()
        name = str(params.get("name") or "").strip()
        return {
            "kind": "jira_version_create",
            "title": "Create Jira version",
            "summary": f"{project_key or 'project'} / {name or 'version'}",
            "after": {
                "project_key": project_key,
                "name": name,
                "description": str(params.get("description") or "").strip(),
                "release_date": str(params.get("release_date") or "").strip(),
                "start_date": str(params.get("start_date") or "").strip(),
            },
            "details": ["A new Jira release/version will be created with these values."],
        }

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip().upper()
        name = str(params.get("name") or "").strip()
        if not project_key or not name:
            return {"error": "project_key and name are required"}

        allowed = _jira_allowed_projects(context)
        if allowed and project_key not in allowed:
            return {"error": f"Project '{project_key}' is not in the allowed list: {allowed}"}
        blocked = await _maybe_block_change_with_approval(
            self.name,
            params,
            context,
            action_title=f"Create Jira version in {project_key}",
        )
        if blocked is not None:
            return blocked

        request = VersionRequest(
            project_key=project_key,
            name=name,
            description=str(params.get("description") or "").strip(),
            release_date=_normalize_requested_release_date(str(params.get("release_date") or "").strip(), context),
            start_date=params.get("start_date"),
        )
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            return await upsert_version(client, jira_url, headers=headers, request=request)


class ReleaseJiraVersion:
    name = "release_jira_version"
    description = "Mark a Jira version as released."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        jira_url = _jira_base_url(context)
        if not jira_url:
            return {"error": "No Jira URL configured for this project"}

        version_id = str(params.get("version_id") or "").strip()
        if not version_id:
            return {"error": "version_id is required"}

        release_date = _normalize_requested_release_date(
            str(params.get("release_date") or "").strip(),
            context,
        )
        payload: dict[str, Any] = {"released": True}
        if release_date:
            payload["releaseDate"] = release_date

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            **_jira_auth_headers(context),
        }
        async with httpx.AsyncClient(**_jira_http(context), transport=egress_transport(CONNECTION_JIRA)) as client:
            status_code = await _jira_helpers_api._jira_api_put(
                client, jira_url, f"/version/{version_id}", headers=headers, payload=payload
            )

        return {
            "version_id": version_id,
            "status_code": status_code,
            "status": "released",
        }
