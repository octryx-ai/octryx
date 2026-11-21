"""Provider-owned GitHub source-control tools."""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

from ...services.outbound_egress import CONNECTION_GITHUB
from ...services.source_control import SourceControlOperation
from ..context import ToolContext
from .common import _limit, _string, connection_http_json
from .github import _github_base_url, _github_headers, _resolve_github_repo
from .github_source_control_common import github_source_control_metadata, require_github_repository_operation
from .source_control_evidence import github_web_base, with_github_branch_source, with_web_url_source

_http_json = connection_http_json(CONNECTION_GITHUB)


def _git_failure(error: str, exit_code: int, stderr: str = "") -> dict[str, Any]:
    """A failed git step: its class and git's last line with secrets removed (``git_errors``), never more."""
    from .git_errors import git_failure

    return git_failure(error, exit_code, stderr)


async def _github_default_branch(context: ToolContext, owner: str, repo: str) -> str:
    data = await _http_json(
        "GET",
        f"{_github_base_url(context)}/repos/{owner}/{repo}",
        headers=await _github_headers(context),
    )
    return _string(data.get("default_branch") or "main") or "main"


async def _github_branch_sha(context: ToolContext, owner: str, repo: str, ref: str) -> str:
    normalized_ref = _string(ref)
    if len(normalized_ref) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in normalized_ref):
        return normalized_ref
    data = await _http_json(
        "GET",
        f"{_github_base_url(context)}/repos/{owner}/{repo}/git/ref/heads/{quote(normalized_ref, safe='/')}",
        headers=await _github_headers(context),
    )
    obj = data.get("object") or {}
    sha = _string(obj.get("sha"))
    if not sha:
        raise ValueError("GitHub branch start point did not return a commit sha")
    return sha


class ReadGitHubFileTool:
    name = "read_github_file"
    description = "Read a file from a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        path = _string(params.get("path"))
        if not owner or not repo or not path:
            return {"error": "repository and path are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        query: dict[str, Any] = {}
        ref = _string(params.get("ref"))
        if ref:
            query["ref"] = ref
        data = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/contents/{quote(path, safe='/')}",
            headers=await _github_headers(context),
            params=query,
        )
        encoded = _string(data.get("content")).replace("\n", "")
        content = base64.b64decode(encoded.encode()).decode("utf-8", errors="replace") if encoded else ""
        result = {
            "repository": f"{owner}/{repo}",
            "path": path,
            "ref": ref or data.get("sha"),
            "content": content,
            "encoding": data.get("encoding"),
            "size": data.get("size"),
        }
        # The file's own API web URL, only on the configured GitHub web host (evidence fields).
        result = with_web_url_source(
            {**result, "html_url": data.get("html_url")},
            github_web_base(context),
            url_field="html_url",
            title=f"{owner}/{repo}: {path}",
        )
        result["source_control"] = github_source_control_metadata(
            SourceControlOperation.READ_FILE,
            owner=owner,
            repo=repo,
            status="read",
            output={"path": path, "content_hash": _string(data.get("sha"))},
            evidence={"ref": ref or ""},
        )
        return result


class ListGitHubBranchesTool:
    name = "list_github_branches"
    description = "List branches for a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        if not owner or not repo:
            return {"error": "repository is required and must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="read")
        if denied:
            return denied
        limit = _limit(context, params, default=100, maximum=200)
        data = await _http_json(
            "GET",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/branches",
            headers=await _github_headers(context),
            params={"per_page": limit},
        )
        web_base = github_web_base(context)
        # Each branch names its tree page on the configured GitHub web host (evidence fields).
        branches = [
            with_github_branch_source(
                {
                    "name": branch.get("name"),
                    "latest_commit": (branch.get("commit") or {}).get("sha"),
                    "protected": branch.get("protected", False),
                },
                web_base,
                owner,
                repo,
            )
            for branch in data[:limit]
        ]
        return {
            "repository": f"{owner}/{repo}",
            "branches": branches,
            "source_control": github_source_control_metadata(
                SourceControlOperation.LIST_BRANCHES,
                owner=owner,
                repo=repo,
                status="listed",
                output={"branch_count": len(branches)},
                evidence={},
            ),
        }


class CreateGitHubBranchTool:
    name = "create_github_branch"
    description = "Create a branch in a configured GitHub repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        owner, repo = _resolve_github_repo(context, params)
        branch_name = _string(params.get("branch_name"))
        if not owner or not repo or not branch_name:
            return {"error": "repository and branch_name are required and repository must be allowed"}
        denied = await require_github_repository_operation(context, owner=owner, repo=repo, operation="branch")
        if denied:
            return denied
        start_point = _string(params.get("start_point")) or await _github_default_branch(context, owner, repo)
        sha = await _github_branch_sha(context, owner, repo, start_point)
        body = await _http_json(
            "POST",
            f"{_github_base_url(context)}/repos/{owner}/{repo}/git/refs",
            headers=await _github_headers(context),
            json_body={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        return {
            "repository": f"{owner}/{repo}",
            "branch_name": branch_name,
            "start_point": start_point,
            "latest_commit": sha,
            "ref": body.get("ref"),
            "status": "created",
            "source_control": github_source_control_metadata(
                SourceControlOperation.CREATE_BRANCH,
                owner=owner,
                repo=repo,
                status="created",
                output={"branch_name": branch_name, "start_point": start_point, "latest_commit": sha},
                evidence={"provider_operation": "github_branch_create"},
            ),
        }
