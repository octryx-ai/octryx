"""Bitbucket delivery tools on both deployments: a pull request comment and the build statuses of a commit."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.project_resource_policy import require_project_repository_operation
from . import _bitbucket_cloud_ops as cloud_ops
from . import _bitbucket_internal_network
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_failure
from ._bitbucket_internal_core import _bitbucket_base_url, _is_repo_allowed
from ._bitbucket_internal_network import _bitbucket_json_post
from ._bitbucket_write_gate import bitbucket_write_refusal

MAX_COMMENT_CHARS = 32000
# A pull request id and a commit go into REST paths: only their own shapes, never a path segment (review fix 1).
PR_ID = re.compile(r"^\d{1,10}$")
COMMIT = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _repository(params: dict, context: ToolContext) -> tuple[str, str, dict[str, Any] | None]:
    project_key = str(params.get("project_key") or "").strip()
    repo_slug = str(params.get("repo_slug") or "").strip()
    if not _bitbucket_base_url(context):
        return project_key, repo_slug, {"error": "No Bitbucket URL configured for this project"}
    if not project_key or not repo_slug:
        return project_key, repo_slug, {"error": "project_key and repo_slug are required"}
    if not _is_repo_allowed(context, project_key, repo_slug):
        return project_key, repo_slug, {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
    return project_key, repo_slug, None


async def _server_pr_id(context: ToolContext, project_key: str, repo_slug: str, from_branch: str) -> str:
    from ._bitbucket_pull_requests import _find_open_pull_request_for_branch

    pr = await _find_open_pull_request_for_branch(context, project_key, repo_slug, from_branch)
    return str((pr or {}).get("id") or "")


class AddBitbucketPullRequestComment:
    name = "add_bitbucket_pull_request_comment"
    description = "Comment on a pull request of an allowed Bitbucket repository (by id or by its source branch)."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_key, repo_slug, refused = _repository(params, context)
        if refused:
            return refused
        text = str(params.get("text") or "").strip()[:MAX_COMMENT_CHARS]
        pr_id, from_branch = str(params.get("pr_id") or "").strip(), str(params.get("from_branch") or "").strip()
        if not text or not (pr_id or from_branch):
            return {"error": "text and pr_id or from_branch are required"}
        if pr_id and not PR_ID.fullmatch(pr_id):
            return {"error": "pr_id is a pull request number"}
        try:
            await require_project_repository_operation(
                context.db, project_ids=context.project_ids, provider="bitbucket", operation="pr",
                repository_refs=[repo_slug, f"{project_key}/{repo_slug}"],
            )
        except HTTPException as exc:
            return {"error": exc.detail}
        if refused := await bitbucket_write_refusal(context, project_key=project_key, repo_slug=repo_slug):
            return refused
        try:
            if cloud_context(context):
                if not pr_id:
                    pr = await cloud_ops.find_open_pr(context, project_key, repo_slug, from_branch)
                    pr_id = str((pr or {}).get("id") or "")
                if not pr_id:
                    return {"error": f"No open pull request of branch {from_branch}"}
                posted = await cloud_ops.comment_pr(context, project_key, repo_slug, pr_id, text)
            else:
                pr_id = pr_id or await _server_pr_id(context, project_key, repo_slug, from_branch)
                if not pr_id:
                    return {"error": f"No open pull request of branch {from_branch}"}
                body, _ = await _bitbucket_json_post(
                    context, f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}/comments",
                    payload={"text": text})
                posted = {"comment_id": (body or {}).get("id"), "url": ""}
        except CloudApiError as error:
            return cloud_failure(error)
        return {"status": "created", "project_key": project_key, "repo_slug": repo_slug, "pr_id": pr_id, **posted}


async def _attach_test_cases(context: ToolContext, project_key: str, repo_slug: str,
                             statuses: list[dict[str, Any]]) -> None:
    for status in statuses:
        if number := cloud_ops.pipeline_number(str(status.get("url") or "")):
            try:
                status["test_cases"] = await cloud_ops.pipeline_test_cases(context, project_key, repo_slug, number)
            except CloudApiError as error:
                status["test_report_error"] = {"status_code": error.status, "message": error.message}


class GetBitbucketBuildStatuses:
    name = "get_bitbucket_build_statuses"
    description = "Build statuses (CI) of a commit, or of a branch's head commit, in an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        project_key, repo_slug, refused = _repository(params, context)
        if refused:
            return refused
        commit, branch = str(params.get("commit") or "").strip(), str(params.get("branch") or "").strip()
        if not commit and not branch:
            return {"error": "commit or branch is required"}
        if commit and not COMMIT.fullmatch(commit):
            return {"error": "commit is a commit SHA (7-40 hex characters)"}
        try:
            if cloud_context(context):
                commit = commit or await cloud_ops.branch_head(context, project_key, repo_slug, branch)
                statuses = await cloud_ops.build_statuses(context, project_key, repo_slug, commit) if commit else []
                if params.get("include_test_reports") is True:
                    await _attach_test_cases(context, project_key, repo_slug, statuses)
            else:
                if not commit:
                    branches = await _bitbucket_internal_network._bitbucket_json_get(
                        context, f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches",
                        params={"filterText": branch})
                    commit = next((str(item.get("latestCommit") or "") for item in (branches or {}).get("values") or []
                                   if item.get("displayId") == branch), "")
                payload = await _bitbucket_internal_network._bitbucket_json_get(context, f"/rest/build-status/1.0/commits/{commit}") if commit else {}
                statuses = [{"state": str(item.get("state") or ""), "key": item.get("key"), "name": item.get("name"),
                             "url": item.get("url"), "commit": commit} for item in (payload or {}).get("values") or []]
        except CloudApiError as error:
            return cloud_failure(error)
        if not commit:
            return {"error": f"Branch {branch} not found"}
        return {"project_key": project_key, "repo_slug": repo_slug, "commit": commit, "branch": branch,
                "statuses": statuses}


__all__ = ["AddBitbucketPullRequestComment", "GetBitbucketBuildStatuses"]
