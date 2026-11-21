"""Bitbucket branch management tools."""

from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.project_resource_policy import require_project_repository_operation
from ...services.request_analysis import effective_limit_from_request_analysis
from ...services.source_control import SourceControlOperation
from . import _bitbucket_cloud_ops as cloud_ops
from . import _bitbucket_internal_network
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_failure
from ._bitbucket_evidence import with_branch_source
from ._bitbucket_internal_core import _bitbucket_base_url, _detect_default_branch, _is_repo_allowed
from ._bitbucket_internal_network import _bitbucket_json_post
from ._bitbucket_source_control import bitbucket_source_control_metadata
from ._bitbucket_write_gate import bitbucket_write_refusal


class ListBitbucketBranches:
    name = "list_bitbucket_branches"
    description = "List branches of an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        if not project_key or not repo_slug:
            return {"error": "project_key and repo_slug are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        filter_text = str(params.get("filter") or "").strip()
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=250,
            hard_max=500,
        )
        req_params: dict[str, Any] = {"limit": limit}
        if filter_text:
            req_params["filterText"] = filter_text

        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches",
            params=req_params,
        )
        branches = payload.get("values", [])
        base_url = _bitbucket_base_url(context)
        return {
            "project_key": project_key,
            "repo_slug": repo_slug,
            # Each branch names its browse page on the configured Bitbucket (evidence fields).
            "branches": [
                with_branch_source(
                    {
                        "name": b.get("displayId"),
                        "is_default": b.get("isDefault", False),
                        "latest_commit": b.get("latestCommit"),
                    },
                    base_url,
                    project_key,
                    repo_slug,
                )
                for b in branches
            ],
            "source_control": bitbucket_source_control_metadata(
                SourceControlOperation.LIST_BRANCHES,
                project_key=project_key,
                repo_slug=repo_slug,
                status="listed",
                output={"branch_count": len(branches)},
                evidence={"filter": filter_text},
            ),
        }


class CreateBitbucketBranch:
    name = "create_bitbucket_branch"
    description = "Create a new branch in an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        branch_name = str(params.get("branch_name") or "").strip()
        start_point = str(params.get("start_point") or "").strip()

        if not project_key or not repo_slug or not branch_name:
            return {"error": "project_key, repo_slug and branch_name are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
        try:
            await require_project_repository_operation(
                context.db,
                project_ids=context.project_ids,
                provider="bitbucket",
                operation="branch",
                repository_refs=[repo_slug, f"{project_key}/{repo_slug}"],
            )
        except HTTPException as exc:
            return {"error": exc.detail}
        if refused := await bitbucket_write_refusal(context, project_key=project_key, repo_slug=repo_slug):
            return refused
        if cloud_context(context):
            return await _create_cloud_branch(context, project_key, repo_slug, branch_name, start_point)
        if not start_point:
            start_point = await _detect_default_branch(context, project_key, repo_slug)

        body, status_code = await _bitbucket_json_post(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches",
            payload={"name": branch_name, "startPoint": start_point},
        )
        result = body or {}
        return {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "branch_name": result.get("displayId", branch_name),
            "start_point": start_point,
            "latest_commit": result.get("latestCommit"),
            "status_code": status_code,
            "status": "created",
            "source_control": bitbucket_source_control_metadata(
                SourceControlOperation.CREATE_BRANCH,
                project_key=project_key,
                repo_slug=repo_slug,
                status="created",
                output={
                    "branch_name": result.get("displayId", branch_name),
                    "start_point": start_point,
                    "latest_commit": result.get("latestCommit") or "",
                    "status_code": status_code,
                },
                evidence={"provider_operation": "bitbucket_branch_create"},
            ),
        }


async def _create_cloud_branch(
    context: ToolContext, project_key: str, repo_slug: str, branch_name: str, start_point: str
) -> dict[str, Any]:
    try:
        created = await cloud_ops.create_branch(context, project_key, repo_slug, branch_name, start_point)
    except CloudApiError as error:
        return cloud_failure(error)
    return {
        "project_key": project_key,
        "repo_slug": repo_slug,
        **created,
        "status_code": 201,
        "status": "created",
        "source_control": bitbucket_source_control_metadata(
            SourceControlOperation.CREATE_BRANCH,
            project_key=project_key,
            repo_slug=repo_slug,
            status="created",
            output={**created, "status_code": 201},
            evidence={"provider_operation": "bitbucket_cloud_branch_create"},
        ),
    }
