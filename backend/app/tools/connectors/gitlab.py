"""GitLab connector tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITLAB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from .common import _limit, _normalize_string_list, _string, connection_http_json
from .credential_boundary import connector_secret_value
from .gitlab_source_control_common import gitlab_source_control_metadata, require_gitlab_repository_operation
from .source_control_evidence import gitlab_web_base, with_web_url_source

_http_json = connection_http_json(CONNECTION_GITLAB)


def _gitlab_base_url(context: ToolContext) -> str:
    raw = _string(context.project_config.get("gitlab_url"))
    if not raw:
        return ""
    return raw.rstrip("/") if raw.rstrip("/").endswith("/api/v4") else raw.rstrip("/") + "/api/v4"


async def _gitlab_headers(context: ToolContext) -> dict[str, str]:
    token = await connector_secret_value(context, connector_name="gitlab", field_name="gitlab_token")
    return {"PRIVATE-TOKEN": token} if token else {}


def _gitlab_allowed_projects(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("gitlab_allowed_projects"))


def _resolve_gitlab_project(context: ToolContext, params: dict[str, Any]) -> str | None:
    project = _string(params.get("project") or params.get("project_id"))
    allowed = _gitlab_allowed_projects(context)
    if not project and len(allowed) == 1:
        project = allowed[0]
    if not project:
        return None
    if allowed and project not in allowed:
        return None
    return project


class ListGitLabProjectsTool:
    name = "list_gitlab_projects"
    description = "List GitLab projects visible to the configured connector."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        base = _gitlab_base_url(context)
        if not base:
            return {"error": "No GitLab URL configured for this project"}
        allowed = _gitlab_allowed_projects(context)
        limit = _limit(context, params, default=20, maximum=100)
        items: list[dict[str, Any]] = []
        if allowed:
            for project in allowed[:limit]:
                data = await _http_json(
                    "GET",
                    f"{base}/projects/{quote(project, safe='')}",
                    headers=await _gitlab_headers(context),
                )
                items.append(
                    {
                        "id": data.get("id"),
                        "path_with_namespace": data.get("path_with_namespace"),
                        "default_branch": data.get("default_branch"),
                        "web_url": data.get("web_url"),
                    }
                )
        else:
            group = _string(context.project_config.get("gitlab_group"))
            if group:
                data = await _http_json(
                    "GET",
                    f"{base}/groups/{quote(group, safe='')}/projects",
                    headers=await _gitlab_headers(context),
                    params={"per_page": limit, "order_by": "last_activity_at"},
                )
            else:
                data = await _http_json(
                    "GET",
                    f"{base}/projects",
                    headers=await _gitlab_headers(context),
                    params={"membership": True, "per_page": limit, "order_by": "last_activity_at"},
                )
            for item in data[:limit]:
                items.append(
                    {
                        "id": item.get("id"),
                        "path_with_namespace": item.get("path_with_namespace"),
                        "default_branch": item.get("default_branch"),
                        "web_url": item.get("web_url"),
                    }
                )
        # Each project's own web URL, only on the configured GitLab host (evidence fields).
        web_base = gitlab_web_base(context)
        return {
            "count": len(items),
            "projects": [
                with_web_url_source(item, web_base, url_field="web_url", title=item.get("path_with_namespace") or "")
                for item in items
            ],
        }


class ListGitLabMergeRequestsTool:
    name = "list_gitlab_merge_requests"
    description = "List merge requests for an allowed GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        if not project:
            return {"error": "project is required and must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=20, maximum=100)
        state = _string(params.get("state") or "opened")
        data = await _http_json(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/merge_requests",
            headers=await _gitlab_headers(context),
            params={"state": state, "per_page": limit},
        )
        web_base = gitlab_web_base(context)
        # Each merge request's own web URL, only on the configured GitLab host (evidence fields).
        merge_requests = [
            with_web_url_source(
                {
                    "iid": mr.get("iid"),
                    "title": mr.get("title"),
                    "state": mr.get("state"),
                    "author": (mr.get("author") or {}).get("username"),
                    "updated_at": mr.get("updated_at"),
                    "web_url": mr.get("web_url"),
                },
                web_base,
                url_field="web_url",
                title=f"{project} !{mr.get('iid')}: {mr.get('title') or ''}",
            )
            for mr in data[:limit]
        ]
        return {
            "project": project,
            "count": len(merge_requests),
            "merge_requests": merge_requests,
            "source_control": gitlab_source_control_metadata(
                SourceControlOperation.LIST_CHANGE_REQUESTS,
                project=project,
                status="listed",
                output={"change_request_count": len(merge_requests), "state": state},
                evidence={},
            ),
        }


class ListGitLabPipelinesTool:
    name = "list_gitlab_pipelines"
    description = "List CI/CD pipelines for an allowed GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        if not project:
            return {"error": "project is required and must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=20, maximum=100)
        query: dict[str, Any] = {"per_page": limit}
        ref = _string(params.get("ref"))
        status = _string(params.get("status"))
        if ref:
            query["ref"] = ref
        if status:
            query["status"] = status
        data = await _http_json(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/pipelines",
            headers=await _gitlab_headers(context),
            params=query,
        )
        web_base = gitlab_web_base(context)
        # Each pipeline's own web URL, only on the configured GitLab host (evidence fields).
        pipelines = [
            with_web_url_source(
                {
                    "id": pipe.get("id"),
                    "status": pipe.get("status"),
                    "ref": pipe.get("ref"),
                    "sha": pipe.get("sha"),
                    "updated_at": pipe.get("updated_at"),
                    "web_url": pipe.get("web_url"),
                },
                web_base,
                url_field="web_url",
                title=f"{project} pipeline #{pipe.get('id')}",
            )
            for pipe in data[:limit]
        ]
        return {
            "project": project,
            "count": len(pipelines),
            "pipelines": pipelines,
            "source_control": gitlab_source_control_metadata(
                SourceControlOperation.LIST_PIPELINES,
                project=project,
                status="listed",
                output={"pipeline_count": len(pipelines), "ref": ref, "status": status},
                evidence={},
            ),
        }
