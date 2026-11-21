"""Bitbucket pull request tools."""

from typing import Any

import httpx
from fastapi import HTTPException

from app.tools.context import ToolContext

from ...services.ai_marking import marking_facts, with_marker
from ...services.project_resource_policy import require_project_repository_operation
from ...services.request_analysis import effective_limit_from_request_analysis
from ...services.source_control import SourceControlOperation
from ..scm_requester_rule import apply_requester_rule
from . import _bitbucket_cloud_ops as cloud_ops
from . import _bitbucket_internal_network
from ._bitbucket_cloud import CloudApiError, cloud_context, cloud_failure
from ._bitbucket_delivery import PR_ID
from ._bitbucket_evidence import with_pull_request_source
from ._bitbucket_internal_core import _bitbucket_base_url, _detect_default_branch, _is_repo_allowed
from ._bitbucket_internal_network import _bitbucket_json_post, _bitbucket_json_put
from ._bitbucket_source_control import bitbucket_source_control_metadata
from ._bitbucket_write_gate import bitbucket_write_refusal


def _pr_summary(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pr.get("id"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "description": (pr.get("description") or "")[:500],
        "author": (pr.get("author") or {}).get("user", {}).get("displayName"),
        "from_branch": (pr.get("fromRef") or {}).get("displayId"),
        "to_branch": (pr.get("toRef") or {}).get("displayId"),
        "created_date": pr.get("createdDate"),
        "updated_date": pr.get("updatedDate"),
        "reviewers": [
            {"name": r.get("user", {}).get("displayName"), "approved": r.get("approved", False)}
            for r in pr.get("reviewers") or []
        ],
        "links": (pr.get("links") or {}).get("self", [{}])[0].get("href"),
    }


def _change_request_output(summary: dict[str, Any], *, status_code: int | None = None) -> dict[str, Any]:
    output = {
        "change_request_id": str(summary.get("id") or ""),
        "title": summary.get("title") or "",
        "state": summary.get("state") or "",
        "source_branch": summary.get("from_branch") or "",
        "target_branch": summary.get("to_branch") or "",
        "url": summary.get("links") or "",
    }
    if status_code is not None:
        output["status_code"] = status_code
    return output


def _change_request_source_control(
    operation: SourceControlOperation,
    *,
    project_key: str,
    repo_slug: str,
    status: str,
    summary: dict[str, Any],
    status_code: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return bitbucket_source_control_metadata(
        operation,
        project_key=project_key,
        repo_slug=repo_slug,
        status=status,
        output=_change_request_output(summary, status_code=status_code),
        evidence=evidence or {},
    )


class ListBitbucketPullRequests:
    name = "list_bitbucket_pull_requests"
    description = "List pull requests for an allowed Bitbucket repository. State: OPEN, MERGED, DECLINED, ALL."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        if not project_key or not repo_slug:
            return {"error": "project_key and repo_slug are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        state = str(params.get("state") or "OPEN").strip().upper()
        if state not in ("OPEN", "MERGED", "DECLINED", "ALL"):
            state = "OPEN"
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=100,
            hard_max=200,
        )
        at_branch = str(params.get("branch") or "").strip() or None

        req_params: dict[str, Any] = {"state": state, "limit": limit}
        if at_branch:
            req_params["at"] = at_branch

        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests",
            params=req_params,
        )
        prs = payload.get("values", [])
        # Each pull request names its page on the configured Bitbucket (evidence fields).
        base_url = _bitbucket_base_url(context)
        summaries = [with_pull_request_source(_pr_summary(pr), base_url, project_key, repo_slug) for pr in prs]
        return {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "state": state,
            "pull_requests": summaries,
            "source_control": bitbucket_source_control_metadata(
                SourceControlOperation.LIST_CHANGE_REQUESTS,
                project_key=project_key,
                repo_slug=repo_slug,
                status="listed",
                output={"change_request_count": len(summaries), "state": state},
                evidence={"branch_filter": at_branch or ""},
            ),
        }


class GetBitbucketPullRequest:
    name = "get_bitbucket_pull_request"
    description = "Get details of a specific Bitbucket pull request including activity and diff stat."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        pr_id = str(params.get("pr_id") or "").strip()
        if not project_key or not repo_slug or not pr_id:
            return {"error": "project_key, repo_slug and pr_id are required"}
        if not PR_ID.fullmatch(pr_id):
            return {"error": "pr_id is a pull request number"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
        if cloud_context(context):
            try:
                summary = await cloud_ops.get_pr(context, project_key, repo_slug, pr_id)
            except CloudApiError as error:
                return cloud_failure(error)
            return {**summary, "source_control": _change_request_source_control(
                SourceControlOperation.GET_CHANGE_REQUEST, project_key=project_key, repo_slug=repo_slug,
                status="read", summary=summary)}

        base = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}"
        pr = await _bitbucket_internal_network._bitbucket_json_get(context, base)

        # Fetch diff stat (files changed)
        diff_stat: list[dict] = []
        try:
            diff_payload = await _bitbucket_internal_network._bitbucket_json_get(context, f"{base}/diff", params={"withComments": "false"})
            for d in (diff_payload.get("diffs") or [])[:50]:
                dst = (d.get("destination") or {}).get("toString", "")
                src = (d.get("source") or {}).get("toString", "")
                diff_stat.append({"path": dst or src, "type": "MODIFY" if dst and src else "ADD" if dst else "DELETE"})
        except Exception:
            pass

        # Fetch comments
        comments: list[dict] = []
        try:
            activity_payload = await _bitbucket_internal_network._bitbucket_json_get(context, f"{base}/activities", params={"limit": 20})
            for item in activity_payload.get("values", []):
                if item.get("action") == "COMMENTED":
                    c = item.get("comment") or {}
                    comments.append(
                        {
                            "author": (c.get("author") or {}).get("displayName"),
                            "text": (c.get("text") or "")[:300],
                            "created_date": c.get("createdDate"),
                        }
                    )
        except Exception:
            pass

        result = with_pull_request_source(_pr_summary(pr), _bitbucket_base_url(context), project_key, repo_slug)
        result["diff_stat"] = diff_stat
        result["comments"] = comments
        result["source_control"] = _change_request_source_control(
            SourceControlOperation.GET_CHANGE_REQUEST,
            project_key=project_key,
            repo_slug=repo_slug,
            status="read",
            summary=result,
            evidence={"diff_file_count": len(diff_stat), "comment_count": len(comments)},
        )
        return result


class CreateBitbucketPullRequest:
    name = "create_bitbucket_pull_request"
    description = "Create a new pull request in an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        title = str(params.get("title") or "").strip()
        from_branch = str(params.get("from_branch") or "").strip()

        if not project_key or not repo_slug or not title or not from_branch:
            return {"error": "project_key, repo_slug, title and from_branch are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
        try:
            await require_project_repository_operation(
                context.db,
                project_ids=context.project_ids,
                provider="bitbucket",
                operation="pr",
                repository_refs=[repo_slug, f"{project_key}/{repo_slug}"],
            )
        except HTTPException as exc:
            return {"error": exc.detail}
        if refused := await bitbucket_write_refusal(context, project_key=project_key, repo_slug=repo_slug):
            return refused
        if cloud_context(context):
            return await _create_cloud_pull_request(context, params, project_key, repo_slug, title, from_branch)

        to_branch = str(params.get("to_branch") or "").strip()
        if not to_branch:
            to_branch = await _detect_default_branch(context, project_key, repo_slug)

        description = str(params.get("description") or "").strip()
        existing = await _find_open_pull_request_for_branch(context, project_key, repo_slug, from_branch)
        if existing is not None:
            summary = _pr_summary(existing)
            return {
                **summary,
                "status": "existing",
                "status_code": 200,
                "project_key": project_key,
                "repo_slug": repo_slug,
                "delivery_contract": {
                    "version": "bitbucket_pr_delivery.v1",
                    "deduplicated": True,
                    "reason": "open_pull_request_for_source_branch_exists",
                },
                "source_control": _change_request_source_control(
                    SourceControlOperation.CREATE_CHANGE_REQUEST,
                    project_key=project_key,
                    repo_slug=repo_slug,
                    status="existing",
                    summary=summary,
                    status_code=200,
                    evidence={
                        "deduplicated": True,
                        "source_branch": from_branch,
                        "target_branch": to_branch,
                    },
                ),
            }

        from ...services.secure_work.coding.coding_pr_delivery import reviewer_contract_for_bitbucket_pr_tool

        reviewer_contract = await reviewer_contract_for_bitbucket_pr_tool(
            context.db,
            session_id=context.session_id,
            project_key=project_key,
            repo_slug=repo_slug,
            from_branch=from_branch,
            explicit_reviewers=params.get("reviewers"),
        )
        reviewer_names = list(reviewer_contract.get("reviewers") or [])
        reviewer_names, description, skipped = apply_requester_rule(
            reviewer_names, requester=str(params.get("requester") or "").strip(),
            author=str(context.project_config.get("bitbucket_username") or "").strip(), description=description,
            mention=f"@{str(params.get('requester') or '').strip()}")
        description = with_marker(description, await marking_facts(context))

        payload: dict[str, Any] = {
            "title": title,
            "description": description,
            "fromRef": {
                "id": f"refs/heads/{from_branch}",
                "repository": {"slug": repo_slug, "project": {"key": project_key}},
            },
            "toRef": {
                "id": f"refs/heads/{to_branch}",
                "repository": {"slug": repo_slug, "project": {"key": project_key}},
            },
        }
        if reviewer_names:
            payload["reviewers"] = [{"user": {"name": r}} for r in reviewer_names]

        body, status_code = await _bitbucket_json_post(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests",
            payload=payload,
        )
        result = body or {}
        summary = _pr_summary(result)
        return {
            **summary,
            "status_code": status_code,
            "status": "created",
            "project_key": project_key,
            "repo_slug": repo_slug,
            **({"reviewer_skipped": skipped} if skipped else {}),
            "delivery_contract": {
                "version": "bitbucket_pr_delivery.v1",
                "deduplicated": False,
                "reviewer_source": reviewer_contract.get("source"),
                "reviewers": reviewer_names,
                "missing_setup": reviewer_contract.get("missing_setup") or [],
                "recommendation_evidence": reviewer_contract.get("recommendation_evidence") or [],
            },
            "source_control": _change_request_source_control(
                SourceControlOperation.CREATE_CHANGE_REQUEST,
                project_key=project_key,
                repo_slug=repo_slug,
                status="created",
                summary=summary,
                status_code=status_code,
                evidence={
                    "deduplicated": False,
                    "reviewer_source": reviewer_contract.get("source") or "",
                    "reviewer_count": len(reviewer_names),
                    "source_branch": from_branch,
                    "target_branch": to_branch,
                },
            ),
        }


class UpdateBitbucketPullRequest:
    name = "update_bitbucket_pull_request"
    description = "Update title, description, target branch, or reviewers of an allowed Bitbucket pull request."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        if not _bitbucket_base_url(context):
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        pr_id = str(params.get("pr_id") or "").strip()
        if not project_key or not repo_slug or not pr_id:
            return {"error": "project_key, repo_slug and pr_id are required"}
        if not PR_ID.fullmatch(pr_id):
            return {"error": "pr_id is a pull request number"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}
        if not any(key in params for key in ("title", "description", "to_branch", "reviewers")):
            return {"error": "At least one of title, description, to_branch or reviewers is required"}
        try:
            await require_project_repository_operation(
                context.db,
                project_ids=context.project_ids,
                provider="bitbucket",
                operation="pr",
                repository_refs=[repo_slug, f"{project_key}/{repo_slug}"],
            )
        except HTTPException as exc:
            return {"error": exc.detail}
        if refused := await bitbucket_write_refusal(context, project_key=project_key, repo_slug=repo_slug):
            return refused

        base = f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests/{pr_id}"
        existing = await _bitbucket_internal_network._bitbucket_json_get(context, base)
        version = existing.get("version")
        if version is None:
            return {"error": "Bitbucket pull request version is required for update"}

        title = str(params.get("title") or existing.get("title") or "").strip()
        description = str(params.get("description") or existing.get("description") or "").strip()
        existing_from_ref = existing.get("fromRef") or {}
        existing_to_ref = existing.get("toRef") or {}
        to_branch = str(params.get("to_branch") or existing_to_ref.get("displayId") or "").strip()
        if not title or not to_branch:
            return {"error": "Updated title and target branch are required"}

        payload: dict[str, Any] = {
            "id": existing.get("id"),
            "version": version,
            "title": title,
            "description": description,
            "fromRef": existing_from_ref,
            "toRef": {
                **existing_to_ref,
                "id": f"refs/heads/{to_branch}",
                "displayId": to_branch,
                "repository": {"slug": repo_slug, "project": {"key": project_key}},
            },
        }
        if "reviewers" in params:
            reviewer_names = [str(item or "").strip() for item in params.get("reviewers") or [] if str(item or "").strip()]
            payload["reviewers"] = [{"user": {"name": reviewer}} for reviewer in reviewer_names]
        else:
            payload["reviewers"] = existing.get("reviewers") or []

        body, status_code = await _bitbucket_json_put(context, base, payload=payload)
        result = body or {}
        summary = _pr_summary(result)
        return {
            **summary,
            "status_code": status_code,
            "status": "updated",
            "project_key": project_key,
            "repo_slug": repo_slug,
            "source_control": _change_request_source_control(
                SourceControlOperation.UPDATE_CHANGE_REQUEST,
                project_key=project_key,
                repo_slug=repo_slug,
                status="updated",
                summary=summary,
                status_code=status_code,
                evidence={
                    "updated_fields": [
                        field for field in ("title", "description", "to_branch", "reviewers") if field in params
                    ],
                    "target_branch": to_branch,
                },
            ),
        }


async def _create_cloud_pull_request(
    context: ToolContext, params: dict, project_key: str, repo_slug: str, title: str, from_branch: str
) -> dict[str, Any]:
    """Bitbucket Cloud: reviewers are Atlassian account ids, named explicitly (the workflow resolves the requester)."""
    reviewers = [str(item or "").strip() for item in params.get("reviewers") or [] if str(item or "").strip()]
    try:
        result = await cloud_ops.create_pr(
            context, project_key, repo_slug, title=title, description=str(params.get("description") or "").strip(),
            from_branch=from_branch, to_branch=str(params.get("to_branch") or "").strip(), reviewers=reviewers,
            requester=str(params.get("requester") or "").strip(), marking=await marking_facts(context))
    except CloudApiError as error:
        return cloud_failure(error)
    if result.get("error"):
        return result
    status = str(result.get("status") or "created")
    return {
        **result,
        "status_code": 200 if status == "existing" else 201,
        "project_key": project_key,
        "repo_slug": repo_slug,
        "delivery_contract": {"version": "bitbucket_pr_delivery.v1", "deduplicated": status == "existing",
                              "reviewer_source": "explicit", "reviewers": reviewers},
        "source_control": _change_request_source_control(
            SourceControlOperation.CREATE_CHANGE_REQUEST, project_key=project_key, repo_slug=repo_slug,
            status=status, summary=result, evidence={"deduplicated": status == "existing",
                                                     "reviewer_count": len(reviewers), "source_branch": from_branch}),
    }


async def _find_open_pull_request_for_branch(
    context: ToolContext,
    project_key: str,
    repo_slug: str,
    from_branch: str,
) -> dict[str, Any] | None:
    try:
        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/pull-requests",
            params={"state": "OPEN", "limit": 100},
        )
    except httpx.HTTPError:
        return None
    for pr in payload.get("values") or []:
        source_branch = str(((pr.get("fromRef") or {}).get("displayId")) or "").strip()
        if source_branch == from_branch:
            return pr
    return None
