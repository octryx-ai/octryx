"""Provider-owned GitHub pull request tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ...services.outbound_egress import CONNECTION_GITHUB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from ..scm_requester_rule import REVIEWER_REFUSED, apply_requester_rule, connection_author
from .common import _string, connection_http_json
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .github_source_control import _github_default_branch
from .github_source_control_common import github_source_control_metadata, require_github_repository_operation
from .source_control_evidence import github_web_base, with_github_item_source

_http_json = connection_http_json(CONNECTION_GITHUB)


def _pr_summary(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "merged": pr.get("merged"),
        "author": (pr.get("user") or {}).get("login"),
        "from_branch": (pr.get("head") or {}).get("ref"),
        "to_branch": (pr.get("base") or {}).get("ref"),
        "created_at": pr.get("created_at"),
        "updated_at": pr.get("updated_at"),
        "html_url": pr.get("html_url"),
    }


def _change_request_output(summary: dict[str, Any], *, status_code: int | None = None) -> dict[str, Any]:
    output = {
        "change_request_id": str(summary.get("number") or ""),
        "title": summary.get("title") or "",
        "state": summary.get("state") or "",
        "source_branch": summary.get("from_branch") or "",
        "target_branch": summary.get("to_branch") or "",
        "url": summary.get("html_url") or "",
    }
    if status_code is not None:
        output["status_code"] = status_code
    return output


def _change_request_source_control(
    operation: SourceControlOperation,
    *,
    owner: str,
    repo: str,
    status: str,
    summary: dict[str, Any],
    status_code: int | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return github_source_control_metadata(
        operation,
        owner=owner,
        repo=repo,
        status=status,
        output=_change_request_output(summary, status_code=status_code),
        evidence=evidence or {},
    )


class GetGitHubPullRequestTool:
    name = "get_github_pull_request"
    description = "Get details of a configured GitHub repository pull request."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        pr_number = _string(params.get("pr_number") or params.get("number"))
        if not owner or not repo or not pr_number:
            return {"error": "repository and pr_number are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        pr = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/pulls/{quote(pr_number, safe='')}",
            headers=await _github_headers(context),
        )
        # The pull request's page on the configured GitHub web host (evidence fields).
        result = with_github_item_source(_pr_summary(pr), github_web_base(context), owner, repo, "pull", label="PR")
        result["repository"] = f"{owner}/{repo}"
        result["source_control"] = _change_request_source_control(
            SourceControlOperation.GET_CHANGE_REQUEST,
            owner=owner,
            repo=repo,
            status="read",
            summary=result,
        )
        return result


async def _requester_rule(
    context: ToolContext, requester: str, reviewers: list[str], body: str
) -> tuple[list[str], str, str, str]:
    skipped, author = "", ""
    if requester and reviewers:
        async def login() -> str:
            me = await _http_json("GET", f"{_github_base_url(context)}/user", headers=await _github_headers(context))
            return _string((me or {}).get("login"))

        author = await connection_author("github", login)
        reviewers, body, skipped = apply_requester_rule(
            reviewers, requester=requester, author=author, description=body, mention=f"@{requester}")
    return reviewers, body, skipped, author


async def _request_reviewers(
    context: ToolContext, owner: str, repo: str, number: Any, reviewers: list[str]
) -> list[str]:
    try:
        review = await _http_json(
            "POST",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/pulls/{number}/requested_reviewers",
            headers=await _github_headers(context),
            json_body={"reviewers": reviewers},
        )
    except httpx.HTTPStatusError:
        # The pull request exists: a refused reviewer request never turns it into a failed step.
        review = {}
    return [str(user.get("login")) for user in (review or {}).get("requested_reviewers") or []
            if isinstance(user, dict) and user.get("login")]


class CreateGitHubPullRequestTool:
    name = "create_github_pull_request"
    description = "Create a pull request in a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        title = _string(params.get("title"))
        from_branch = _string(params.get("from_branch") or params.get("head"))
        if not owner or not repo or not title or not from_branch:
            return {"error": "repository, title and from_branch are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="pr")
        if denied:
            return denied
        to_branch = _string(params.get("to_branch") or params.get("base")) or await _github_default_branch(
            context, owner, repo
        )
        body = _string(params.get("description") or params.get("body"))
        reviewers = [_string(item) for item in params.get("reviewers") or [] if _string(item)] if isinstance(
            params.get("reviewers"), list) else []
        requester = _string(params.get("requester"))
        reviewers, body, skipped, author = await _requester_rule(context, requester, reviewers, body)
        pr = await _http_json(
            "POST",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/pulls",
            headers=await _github_headers(context),
            json_body={"title": title, "head": from_branch, "base": to_branch, "body": body},
        )
        summary = _pr_summary(pr)
        requested: list[str] = []
        if reviewers and summary.get("number") is not None:
            requested = await _request_reviewers(context, owner, repo, summary["number"], reviewers)
            if not skipped and requester in reviewers and requester not in requested and not author:
                skipped = REVIEWER_REFUSED  # the requester may be the (unknown) author: they review outside GitHub
        return {
            **summary,
            "repository": f"{owner}/{repo}",
            "status": "created",
            "reviewers": requested,
            "reviewers_unresolved": [name for name in reviewers if name not in requested],
            **({"reviewer_skipped": skipped} if skipped else {}),
            "source_control": _change_request_source_control(
                SourceControlOperation.CREATE_CHANGE_REQUEST,
                owner=owner,
                repo=repo,
                status="created",
                summary=summary,
                evidence={"source_branch": from_branch, "target_branch": to_branch},
            ),
        }


class UpdateGitHubPullRequestTool:
    name = "update_github_pull_request"
    description = "Update title, body, base branch, or state of a configured GitHub pull request."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        pr_number = _string(params.get("pr_number") or params.get("number"))
        if not owner or not repo or not pr_number:
            return {"error": "repository and pr_number are required and repository must be allowed"}
        if not any(key in params for key in ("title", "description", "body", "to_branch", "base", "state")):
            return {"error": "At least one of title, description/body, to_branch/base, or state is required"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="pr")
        if denied:
            return denied
        payload: dict[str, Any] = {}
        if "title" in params:
            payload["title"] = _string(params.get("title"))
        if "description" in params or "body" in params:
            payload["body"] = _string(params.get("description") or params.get("body"))
        if "to_branch" in params or "base" in params:
            payload["base"] = _string(params.get("to_branch") or params.get("base"))
        if "state" in params:
            payload["state"] = _string(params.get("state"))
        pr = await _http_json(
            "PATCH",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/pulls/{quote(pr_number, safe='')}",
            headers=await _github_headers(context),
            json_body=payload,
        )
        summary = _pr_summary(pr)
        return {
            **summary,
            "repository": f"{owner}/{repo}",
            "status": "updated",
            "source_control": _change_request_source_control(
                SourceControlOperation.UPDATE_CHANGE_REQUEST,
                owner=owner,
                repo=repo,
                status="updated",
                summary=summary,
                evidence={"updated_fields": sorted(payload)},
            ),
        }
