"""Provider-owned GitLab source-control tools."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITLAB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from ..evidence_fields import item_url, with_source
from .common import _limit, _string, connection_http_json
from .gitlab import _gitlab_base_url, _gitlab_headers, _resolve_gitlab_project
from .gitlab_source_control_common import gitlab_source_control_metadata, require_gitlab_repository_operation
from .source_control_evidence import gitlab_web_base

_http_json = connection_http_json(CONNECTION_GITLAB)


def _git_failure(error: str, exit_code: int, stderr: str = "") -> dict[str, Any]:
    from .git_errors import git_failure

    return git_failure(error, exit_code, stderr)


async def _gitlab_default_branch(context: ToolContext, project: str) -> str:
    data = await _http_json(
        "GET",
        f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}",
        headers=await _gitlab_headers(context),
    )
    return _string(data.get("default_branch") or "main") or "main"


class ReadGitLabFileTool:
    name = "read_gitlab_file"
    description = "Read a file from a configured GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        path = _string(params.get("path"))
        if not project or not path:
            return {"error": "project and path are required and project must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="read")
        if denied:
            return denied
        ref = _string(params.get("ref")) or await _gitlab_default_branch(context, project)
        data = await _http_json(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/repository/files/{quote(path, safe='')}",
            headers=await _gitlab_headers(context),
            params={"ref": ref},
        )
        encoded = _string(data.get("content")).replace("\n", "")
        content = base64.b64decode(encoded.encode()).decode("utf-8", errors="replace") if encoded else ""
        result = {
            "project": project,
            "path": path,
            "ref": ref,
            "content": content,
            "encoding": data.get("encoding"),
            "size": data.get("size"),
        }
        # The file's blob page on the configured GitLab, for a project named by its path (evidence fields).
        web_base = gitlab_web_base(context)
        url = item_url(web_base, project, "-", "blob", ref, path) if web_base and "/" in project else None
        result = with_source(result, title=f"{project}: {path}", url=url)
        result["source_control"] = gitlab_source_control_metadata(
            SourceControlOperation.READ_FILE,
            project=project,
            status="read",
            output={"path": path, "content_hash": _string(data.get("content_sha256") or data.get("blob_id"))},
            evidence={"ref": ref},
        )
        return result


class ListGitLabBranchesTool:
    name = "list_gitlab_branches"
    description = "List branches for a configured GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        if not project:
            return {"error": "project is required and must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=100, maximum=200)
        data = await _http_json(
            "GET",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/repository/branches",
            headers=await _gitlab_headers(context),
            params={"per_page": limit},
        )
        web_base = gitlab_web_base(context)
        # Each branch names its tree page on the configured GitLab, for a project named by its path.
        branches = [
            with_source(
                {
                    "name": branch.get("name"),
                    "latest_commit": (branch.get("commit") or {}).get("id"),
                    "protected": branch.get("protected", False),
                },
                title=f"{project}@{branch.get('name')}",
                url=item_url(web_base, project, "-", "tree", branch.get("name")) if web_base and "/" in project else None,
            )
            for branch in data[:limit]
        ]
        return {
            "project": project,
            "branches": branches,
            "source_control": gitlab_source_control_metadata(
                SourceControlOperation.LIST_BRANCHES,
                project=project,
                status="listed",
                output={"branch_count": len(branches)},
                evidence={},
            ),
        }


class CreateGitLabBranchTool:
    name = "create_gitlab_branch"
    description = "Create a branch in a configured GitLab project."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project = _resolve_gitlab_project(context, params)
        branch_name = _string(params.get("branch_name"))
        if not project or not branch_name:
            return {"error": "project and branch_name are required and project must be allowed"}
        denied = await require_gitlab_repository_operation(context, project=project, operation="branch")
        if denied:
            return denied
        start_point = _string(params.get("start_point") or params.get("ref")) or await _gitlab_default_branch(
            context, project
        )
        body = await _http_json(
            "POST",
            f"{_gitlab_base_url(context)}/projects/{quote(project, safe='')}/repository/branches",
            headers=await _gitlab_headers(context),
            params={"branch": branch_name, "ref": start_point},
        )
        latest_commit = (body.get("commit") or {}).get("id")
        return {
            "project": project,
            "branch_name": body.get("name") or branch_name,
            "start_point": start_point,
            "latest_commit": latest_commit,
            "status": "created",
            "source_control": gitlab_source_control_metadata(
                SourceControlOperation.CREATE_BRANCH,
                project=project,
                status="created",
                output={"branch_name": body.get("name") or branch_name, "start_point": start_point, "latest_commit": latest_commit or ""},
                evidence={"provider_operation": "gitlab_branch_create"},
            ),
        }
