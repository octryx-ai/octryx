"""GitHub connector tools."""

from __future__ import annotations

from typing import Any

from ...services.github_url import normalize_github_api_base_url
from ...services.outbound_egress import CONNECTION_GITHUB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from .common import _headers_with_bearer, _limit, _normalize_string_list, _string, connection_http_json
from .credential_boundary import connector_secret_value
from .github_source_control_common import github_source_control_metadata, require_github_repository_operation
from .source_control_evidence import (
    github_web_base,
    with_github_item_source,
    with_github_repository_source,
    with_web_url_source,
)

_http_json = connection_http_json(CONNECTION_GITHUB)


def _github_base_url(context: ToolContext) -> str:
    return normalize_github_api_base_url(context.project_config.get("github_url"))


def _github_owner(context: ToolContext) -> str:
    return _string(context.project_config.get("github_owner"))


def _github_allowed_repositories(context: ToolContext) -> list[str]:
    return _normalize_string_list(context.project_config.get("github_allowed_repositories"))


def _github_owner_type(context: ToolContext) -> str:
    owner_type = _string(context.project_config.get("github_owner_type") or "org").lower() or "org"
    return "user" if owner_type in {"user", "personal"} else "org"


async def _github_token(context: ToolContext) -> str:
    return await connector_secret_value(context, connector_name="github", field_name="github_token")


async def _github_headers(context: ToolContext) -> dict[str, str]:
    token = await _github_token(context)
    return _headers_with_bearer(
        token or None,
        extra={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _resolve_github_repo(context: ToolContext, params: dict[str, Any]) -> tuple[str | None, str | None]:
    repo = _string(params.get("repository") or params.get("repo"))
    owner = _string(params.get("owner") or _github_owner(context))
    if "/" in repo:
        owner, repo = repo.split("/", 1)
    if not owner or not repo:
        allowed = _github_allowed_repositories(context)
        if len(allowed) == 1 and "/" in allowed[0]:
            owner, repo = allowed[0].split("/", 1)
    if not owner or not repo:
        return None, None
    if _github_allowed_repositories(context):
        full = f"{owner}/{repo}"
        if full not in _github_allowed_repositories(context):
            return None, None
    return owner, repo


class ListGitHubRepositoriesTool:
    name = "list_github_repositories"
    description = "List GitHub repositories visible to the configured connector."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        headers = await _github_headers(context)
        allowed = _github_allowed_repositories(context)
        limit = _limit(context, params, default=20, maximum=100)
        items: list[dict[str, Any]] = []
        base_url = _github_base_url(context)

        if allowed:
            for full_name in allowed[:limit]:
                normalized = full_name if "/" in full_name else f"{_github_owner(context)}/{full_name}".lstrip("/")
                data = await _http_json("GET", f"{base_url}/repos/{normalized}", headers=headers)
                items.append(
                    {
                        "full_name": data.get("full_name"),
                        "private": data.get("private"),
                        "default_branch": data.get("default_branch"),
                        "html_url": data.get("html_url"),
                    }
                )
        else:
            owner = _github_owner(context)
            owner_type = _github_owner_type(context)
            if owner and owner_type == "org":
                endpoint = f"{base_url}/orgs/{owner}/repos"
                params = {"type": "all"}
            elif owner and owner_type == "user":
                endpoint = f"{base_url}/user/repos"
                params = {"affiliation": "owner", "visibility": "all"}
            else:
                endpoint = f"{base_url}/user/repos"
                params = {"affiliation": "owner,collaborator,organization_member", "visibility": "all"}
            repos = await _list_github_repositories_paginated(
                endpoint=endpoint,
                headers=headers,
                params=params,
                limit=limit,
            )
            for repo in repos[:limit]:
                items.append(
                    {
                        "full_name": repo.get("full_name"),
                        "private": repo.get("private"),
                        "default_branch": repo.get("default_branch"),
                        "html_url": repo.get("html_url"),
                    }
                )

        # Each repository names its page on the configured GitHub web host (evidence fields).
        web_base = github_web_base(context)
        return {"count": len(items), "repositories": [with_github_repository_source(item, web_base) for item in items]}


async def _list_github_repositories_paginated(
    *,
    endpoint: str,
    headers: dict[str, str],
    params: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit), 500))
    repos: list[dict[str, Any]] = []
    page = 1
    while len(repos) < safe_limit:
        page_items = await _http_json(
            "GET",
            endpoint,
            headers=headers,
            params={
                **params,
                "per_page": min(100, safe_limit - len(repos)),
                "sort": "updated",
                "page": page,
            },
        )
        if not isinstance(page_items, list) or not page_items:
            break
        repos.extend(page_items[: safe_limit - len(repos)])
        if len(page_items) < 100:
            break
        page += 1
    return repos


class ListGitHubPullRequestsTool:
    name = "list_github_pull_requests"
    description = "List pull requests of an allowed GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=20, maximum=100)
        state = _string(params.get("state") or "open")
        head = _string(params.get("head"))  # "owner:branch": the pull requests of one source branch
        data = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/pulls",
            headers=await _github_headers(context),
            params={"state": state, "per_page": limit, **({"head": head} if head else {})},
        )
        web_base = github_web_base(context)
        # Each pull request names its page on the configured GitHub web host (evidence fields).
        pull_requests = [
            with_github_item_source(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "author": (pr.get("user") or {}).get("login"),
                    "updated_at": pr.get("updated_at"),
                    "html_url": pr.get("html_url"),
                    "head_ref": ((pr.get("head") or {}) if isinstance(pr.get("head"), dict) else {}).get("ref"),
                },
                web_base,
                owner,
                repo,
                "pull",
                label="PR",
            )
            for pr in data[:limit]
        ]
        return {
            "repository": f"{owner}/{repo}",
            "count": len(pull_requests),
            "pull_requests": pull_requests,
            "source_control": github_source_control_metadata(
                SourceControlOperation.LIST_CHANGE_REQUESTS,
                owner=owner,
                repo=repo,
                status="listed",
                output={"change_request_count": len(pull_requests), "state": state},
                evidence={},
            ),
        }


class ListGitHubActionRunsTool:
    name = "list_github_action_runs"
    description = "List GitHub Actions workflow runs for an allowed repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        limit = _limit(context, params, default=20, maximum=100)
        query: dict[str, Any] = {"per_page": limit}
        branch = _string(params.get("branch"))
        status = _string(params.get("status"))
        if branch:
            query["branch"] = branch
        if status:
            query["status"] = status
        data = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/actions/runs",
            headers=await _github_headers(context),
            params=query,
        )
        runs = data.get("workflow_runs") or []
        web_base = github_web_base(context)
        return {
            "repository": f"{owner}/{repo}",
            "count": len(runs),
            # Each run's own page, only on the configured GitHub web host (evidence fields).
            "workflow_runs": [
                with_web_url_source(
                    {
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "event": run.get("event"),
                        "branch": run.get("head_branch"),
                        "head_sha": run.get("head_sha"),
                        "created_at": run.get("created_at"),
                        "html_url": run.get("html_url"),
                    },
                    web_base,
                    url_field="html_url",
                    title=f"{owner}/{repo} run {run.get('name') or ''} #{run.get('id')}",
                )
                for run in runs[:limit]
            ],
        }
