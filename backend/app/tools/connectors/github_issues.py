"""Provider-owned GitHub issue tools."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITHUB
from ..context import ToolContext
from .common import _limit, _string, connection_http_json
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .github_source_control_common import require_github_repository_operation
from .source_control_evidence import github_web_base, with_github_item_source

_http_json = connection_http_json(CONNECTION_GITHUB)


def _issue_summary(issue: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "author": (issue.get("user") or {}).get("login"),
        "assignees": [(assignee or {}).get("login") for assignee in issue.get("assignees") or []],
        "labels": [
            (label or {}).get("name") if isinstance(label, dict) else str(label)
            for label in issue.get("labels") or []
        ],
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "html_url": issue.get("html_url"),
    }


class ListGitHubIssuesTool:
    name = "list_github_issues"
    description = "List issues for a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=50, maximum=100)
        query: dict[str, Any] = {"per_page": limit, "state": _string(params.get("state") or "open") or "open"}
        labels = _string(params.get("labels"))
        since = _string(params.get("since"))
        if labels:
            query["labels"] = labels
        if since:
            query["since"] = since
        data = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/issues",
            headers=await _github_headers(context),
            params=query,
        )
        web_base = github_web_base(context)
        # Each issue names its page on the configured GitHub web host (evidence fields).
        issues = [
            with_github_item_source(_issue_summary(issue), web_base, owner, repo, "issues", label="issue")
            for issue in data[:limit]
            if "pull_request" not in issue
        ]
        return {"repository": f"{owner}/{repo}", "count": len(issues), "issues": issues}


class GetGitHubIssueTool:
    name = "get_github_issue"
    description = "Get details of a configured GitHub repository issue."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        issue_number = _string(params.get("issue_number") or params.get("number"))
        if not owner or not repo or not issue_number:
            return {"error": "repository and issue_number are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        issue = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/issues/{quote(issue_number, safe='')}",
            headers=await _github_headers(context),
        )
        summary = with_github_item_source(
            _issue_summary(issue), github_web_base(context), owner, repo, "issues", label="issue"
        )
        return {"repository": f"{owner}/{repo}", **summary, "body": _string(issue.get("body"))[:4000]}


class CreateGitHubIssueTool:
    name = "create_github_issue"
    description = "Create an issue in a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        title = _string(params.get("title"))
        if not owner or not repo or not title:
            return {"error": "repository and title are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="write")
        if denied:
            return denied
        payload = {
            "title": title,
            "body": _string(params.get("body") or params.get("description")),
            "labels": [str(label).strip() for label in params.get("labels") or [] if str(label).strip()],
            "assignees": [str(assignee).strip() for assignee in params.get("assignees") or [] if str(assignee).strip()],
        }
        issue = await _http_json(
            "POST",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/issues",
            headers=await _github_headers(context),
            json_body=payload,
        )
        return {"repository": f"{owner}/{repo}", "status": "created", **_issue_summary(issue)}


class UpdateGitHubIssueTool:
    name = "update_github_issue"
    description = "Update title, body, state, labels, or assignees of a configured GitHub issue."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        issue_number = _string(params.get("issue_number") or params.get("number"))
        if not owner or not repo or not issue_number:
            return {"error": "repository and issue_number are required and repository must be allowed"}
        if not any(key in params for key in ("title", "body", "description", "state", "labels", "assignees")):
            return {"error": "At least one of title, body/description, state, labels, or assignees is required"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="write")
        if denied:
            return denied
        payload: dict[str, Any] = {}
        if "title" in params:
            payload["title"] = _string(params.get("title"))
        if "body" in params or "description" in params:
            payload["body"] = _string(params.get("body") or params.get("description"))
        if "state" in params:
            payload["state"] = _string(params.get("state"))
        if "labels" in params:
            payload["labels"] = [str(label).strip() for label in params.get("labels") or [] if str(label).strip()]
        if "assignees" in params:
            payload["assignees"] = [
                str(assignee).strip() for assignee in params.get("assignees") or [] if str(assignee).strip()
            ]
        issue = await _http_json(
            "PATCH",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/issues/{quote(issue_number, safe='')}",
            headers=await _github_headers(context),
            json_body=payload,
        )
        return {"repository": f"{owner}/{repo}", "status": "updated", **_issue_summary(issue)}
