"""Bitbucket commit listing and diff utilities."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.tools.context import ToolContext

from ...services.request_analysis import effective_limit_from_request_analysis
from . import _bitbucket_internal_network
from ._bitbucket_evidence import with_commit_source
from ._bitbucket_internal_core import (
    _bitbucket_base_url,
    _commit_summary,
    _is_repo_allowed,
    _list_repo_branch_names,
    _normalize_allowed_repos,
    _should_scan_all_branches,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _fromtimestamp(timestamp_ms: float) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def _author_aliases_from_params(params: dict[str, Any]) -> list[str]:
    aliases: list[str] = []

    def add(value: Any) -> None:
        text = " ".join(str(value or "").strip().split())
        if text and text.lower() not in {item.lower() for item in aliases}:
            aliases.append(text)

    add(params.get("author") or params.get("author_query"))
    raw_aliases = params.get("author_aliases")
    if isinstance(raw_aliases, list):
        for value in raw_aliases:
            add(value)
    return aliases[:12]


def _commit_matches_author(commit: dict[str, Any], aliases: list[str]) -> bool:
    if not aliases:
        return True
    haystack = " ".join(
        str(commit.get(key) or "")
        for key in (
            "author_name",
            "author_email",
        )
    ).lower()
    return any(alias.lower() in haystack for alias in aliases)


async def _default_branch_or_none(context: ToolContext, project_key: str, repo_slug: str) -> str | None:
    """The repository's default branch, or ``None`` when Bitbucket does not name one (never a guessed name)."""
    try:
        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context, f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/branches/default"
        )
    except Exception:
        return None
    return str((payload or {}).get("displayId") or "").strip() or None


class ListBitbucketCommits:
    name = "list_bitbucket_commits"
    description = "List recent commits for an allowed Bitbucket repository, optionally filtered by path or ref."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        bitbucket_url = _bitbucket_base_url(context)
        if not bitbucket_url:
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        path = str(params.get("path") or "").strip().strip("/")
        ref = str(params.get("ref") or "").strip()
        author_aliases = _author_aliases_from_params(params)
        limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("limit"),
            default_if_unspecified=100,
            hard_max=250,
        )
        if not project_key or not repo_slug:
            return {"error": "project_key and repo_slug are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        request_params: dict[str, Any] = {"limit": limit}
        if path:
            request_params["path"] = path
        # Without a ref the answer mixed commits of feature
        # branches into "the latest commits". The default branch is the answer unless the person names a ref.
        effective_ref = ref or await _default_branch_or_none(context, project_key, repo_slug)
        if effective_ref:
            request_params["until"] = effective_ref

        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/commits",
            params=request_params,
        )
        commits = payload.get("values", [])
        summaries = [_commit_summary(commit) for commit in commits]
        # Each commit names its page on the configured Bitbucket (evidence fields).
        filtered = [
            with_commit_source(summary, bitbucket_url, project_key, repo_slug)
            for summary in summaries
            if _commit_matches_author(summary, author_aliases)
        ]
        return {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "path": path or None,
            "ref": effective_ref or None,
            "author_filter": author_aliases or None,
            "total_commit_count": len(filtered),
            "commits": filtered,
        }


class ListRecentBitbucketCommits:
    name = "list_recent_bitbucket_commits"
    description = (
        "List commits from allowed Bitbucket repositories within the last N days, optionally across all branches."
    )

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        bitbucket_url = _bitbucket_base_url(context)
        if not bitbucket_url:
            return {"error": "No Bitbucket URL configured for this project"}

        days = max(1, min(int(params.get("days") or 5), 30))
        per_repo_limit = effective_limit_from_request_analysis(
            snapshot=context.turn_context_snapshot,
            fallback_user_message=context.current_user_message,
            requested_limit=params.get("per_repo_limit"),
            default_if_unspecified=1000,
            hard_max=1000,
        )
        include_empty = bool(params.get("include_empty_repositories", False))
        include_all_branches = _should_scan_all_branches(context, params)
        requested_branches = params.get("branches") if isinstance(params.get("branches"), list) else []
        author_aliases = _author_aliases_from_params(params)

        cutoff = _utc_now() - timedelta(days=days)
        allowed_repos = [repo for repo in _normalize_allowed_repos(context.project_config) if repo.get("enabled", True)]
        repositories: list[dict[str, Any]] = []
        recent_commits: list[dict[str, Any]] = []

        for repo in allowed_repos:
            project_key = repo["project_key"]
            repo_slug = repo["repo_slug"]
            branch_names = await _list_repo_branch_names(
                context,
                project_key=project_key,
                repo_slug=repo_slug,
                include_all_branches=include_all_branches,
                requested_branches=requested_branches,
            )
            commits_by_id: dict[str, dict[str, Any]] = {}
            for branch_name in branch_names:
                start = 0
                while True:
                    payload = await _bitbucket_internal_network._bitbucket_json_get(
                        context,
                        f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/commits",
                        params={"limit": 100, "start": start, "until": branch_name},
                    )
                    values = payload.get("values", []) or []
                    if not values:
                        break
                    reached_cutoff = False
                    for commit in values:
                        timestamp_ms = commit.get("authorTimestamp")
                        if not isinstance(timestamp_ms, int):
                            continue
                        commit_time = _fromtimestamp(timestamp_ms)
                        if commit_time < cutoff:
                            reached_cutoff = True
                            break
                        commit_id = str(commit.get("id") or "").strip()
                        if not commit_id:
                            continue
                        existing = commits_by_id.get(commit_id)
                        if existing is None:
                            summary = _commit_summary(commit)
                            if not _commit_matches_author(summary, author_aliases):
                                continue
                            summary["project_key"] = project_key
                            summary["repo_slug"] = repo_slug
                            summary["repository_label"] = repo.get("label") or f"{project_key}/{repo_slug}"
                            summary["branches"] = [branch_name]
                            # The commit's page on the configured Bitbucket (evidence fields).
                            summary = with_commit_source(summary, bitbucket_url, project_key, repo_slug)
                            commits_by_id[commit_id] = summary
                        else:
                            branches = list(existing.get("branches") or [])
                            if branch_name not in branches:
                                branches.append(branch_name)
                                existing["branches"] = branches
                    if reached_cutoff or payload.get("isLastPage", True):
                        break
                    start = int(payload.get("nextPageStart") or 0)

            filtered = sorted(
                commits_by_id.values(),
                key=lambda item: item.get("author_timestamp") or 0,
                reverse=True,
            )[:per_repo_limit]
            for item in filtered:
                recent_commits.append(item)

            if filtered or include_empty:
                repositories.append(
                    {
                        "project_key": project_key,
                        "repo_slug": repo_slug,
                        "label": repo.get("label") or f"{project_key}/{repo_slug}",
                        "branch_mode": "all" if include_all_branches and not requested_branches else "selected",
                        "branches_scanned": branch_names,
                        "commit_count": len(filtered),
                        "commits": filtered,
                    }
                )

        recent_commits.sort(key=lambda item: item.get("author_timestamp") or 0, reverse=True)
        return {
            "days": days,
            "cutoff_utc": cutoff.isoformat(),
            "branch_mode": "all" if include_all_branches and not requested_branches else "selected",
            "author_filter": author_aliases or None,
            "total_commit_count": len(recent_commits),
            "repositories": repositories,
            "commits": recent_commits,
        }


class GetBitbucketCommitChanges:
    name = "get_bitbucket_commit_changes"
    description = "List changed files for a specific commit in an allowed Bitbucket repository."

    async def execute(self, params: dict, context: ToolContext) -> dict[str, Any]:
        bitbucket_url = _bitbucket_base_url(context)
        if not bitbucket_url:
            return {"error": "No Bitbucket URL configured for this project"}

        project_key = str(params.get("project_key") or "").strip()
        repo_slug = str(params.get("repo_slug") or "").strip()
        commit_id = str(params.get("commit_id") or "").strip()
        limit = max(1, min(int(params.get("limit") or 100), 200))
        if not project_key or not repo_slug or not commit_id:
            return {"error": "project_key, repo_slug and commit_id are required"}
        if not _is_repo_allowed(context, project_key, repo_slug):
            return {"error": f"Repository {project_key}/{repo_slug} is not allowed for this project"}

        payload = await _bitbucket_internal_network._bitbucket_json_get(
            context,
            f"/rest/api/1.0/projects/{project_key}/repos/{repo_slug}/commits/{commit_id}/changes",
            params={"limit": limit},
        )
        values = payload.get("values", [])
        result = {
            "project_key": project_key,
            "repo_slug": repo_slug,
            "commit_id": commit_id,
            "changes": [
                {
                    "path": "/".join((change.get("path") or {}).get("components", [])),
                    "type": change.get("type"),
                    "src_path": "/".join((change.get("srcPath") or {}).get("components", [])),
                    "executable": change.get("executable"),
                }
                for change in values
            ],
        }
        # The commit's page on the configured Bitbucket (evidence fields).
        return with_commit_source(result, bitbucket_url, project_key, repo_slug)
