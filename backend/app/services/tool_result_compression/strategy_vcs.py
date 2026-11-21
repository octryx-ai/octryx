from __future__ import annotations

from typing import Any

from app.services.answer_evidence.fields import source_subset
from app.services.tool_result_compression.budget import COMPACT_RESULT_TOKEN_BUDGET_KEY
from app.services.tool_result_compression.config import clamp_config_int


def _truncate_text(value: Any, *, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return text[: max_chars - 3].rstrip() + "..."


def _increment_count(values: dict[str, int], value: Any) -> None:
    normalized = str(value or "").strip()
    if not normalized:
        return
    values[normalized] = values.get(normalized, 0) + 1


def _compact_count_map(values: dict[str, int], *, limit: int) -> dict[str, int]:
    return dict(sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit])


def _compress_recent_bitbucket_commits(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_repositories = clamp_config_int(
        config,
        "max_repositories",
        default=10,
        minimum=1,
        maximum=50,
    )
    max_commits_per_repo = clamp_config_int(
        config,
        "max_commits_per_repo",
        default=3,
        minimum=1,
        maximum=20,
    )
    max_global_commits = clamp_config_int(
        config,
        "max_global_commits",
        default=12,
        minimum=1,
        maximum=100,
    )
    max_message_chars = clamp_config_int(config, "max_message_chars", default=140, minimum=80, maximum=400)
    compact_token_budget = clamp_config_int(
        config,
        "compact_token_budget",
        default=4500,
        minimum=3000,
        maximum=8000,
    )

    repositories: list[dict[str, Any]] = []
    all_repositories = result.get("repositories") or []
    all_commits = result.get("commits") or []
    repository_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    branch_counts: dict[str, int] = {}
    for repo in all_repositories:
        label = str(repo.get("label") or f"{repo.get('project_key')}/{repo.get('repo_slug')}").strip()
        if label:
            repository_counts[label] = int(repo.get("commit_count") or 0)
    for commit in all_commits:
        _increment_count(author_counts, commit.get("author_name"))
        for branch in commit.get("branches") or []:
            _increment_count(branch_counts, branch)

    sorted_repositories = sorted(
        all_repositories,
        key=lambda item: (-(int(item.get("commit_count") or 0)), str(item.get("label") or "")),
    )
    for repo in sorted_repositories[:max_repositories]:
        commits: list[dict[str, Any]] = []
        repo_branch_counts: dict[str, int] = {}
        for commit in (repo.get("commits") or [])[:max_commits_per_repo]:
            branches = [str(branch).strip() for branch in (commit.get("branches") or []) if str(branch).strip()]
            for branch in branches:
                repo_branch_counts[branch] = repo_branch_counts.get(branch, 0) + 1
            commits.append(
                {
                    "display_id": commit.get("display_id"),
                    "message": _truncate_text(commit.get("message"), max_chars=max_message_chars),
                    "author_name": commit.get("author_name"),
                    "author_timestamp": commit.get("author_timestamp"),
                    "branches": branches[:5],
                    **source_subset(commit),
                }
            )
        repositories.append(
            {
                "label": repo.get("label") or f"{repo.get('project_key')}/{repo.get('repo_slug')}",
                "project_key": repo.get("project_key"),
                "repo_slug": repo.get("repo_slug"),
                "commit_count": repo.get("commit_count"),
                "branches_scanned": (repo.get("branches_scanned") or [])[:12],
                "branch_mode": repo.get("branch_mode"),
                "top_branches": sorted(repo_branch_counts.items(), key=lambda item: (-item[1], item[0]))[:5],
                "recent_commits": commits,
            }
        )

    commits: list[dict[str, Any]] = []
    for commit in all_commits[:max_global_commits]:
        commits.append(
            {
                "repository_label": commit.get("repository_label")
                or f"{commit.get('project_key')}/{commit.get('repo_slug')}",
                "display_id": commit.get("display_id"),
                "message": _truncate_text(commit.get("message"), max_chars=max_message_chars),
                "author_name": commit.get("author_name"),
                "author_timestamp": commit.get("author_timestamp"),
                "branches": (commit.get("branches") or [])[:5],
                **source_subset(commit),
            }
        )

    return {
        "days": result.get("days"),
        "cutoff_utc": result.get("cutoff_utc"),
        "branch_mode": result.get("branch_mode"),
        "author_filter": result.get("author_filter"),
        "total_commit_count": result.get("total_commit_count"),
        "repository_count": len(all_repositories),
        "returned_repository_count": len(repositories),
        "omitted_repository_count": max(0, len(all_repositories) - len(repositories)),
        "returned_global_commit_count": len(commits),
        "omitted_global_commit_count": max(0, len(all_commits) - len(commits)),
        "repository_commit_counts": _compact_count_map(repository_counts, limit=12),
        "author_counts": _compact_count_map(author_counts, limit=10),
        "branch_counts": _compact_count_map(branch_counts, limit=10),
        "repositories": repositories,
        "recent_commits": commits,
        "answer_guidance": {
            "use_counts_before_examples": True,
            "raw_payload_available_as_artifact": True,
            "interpretation": (
                "Counts describe the full returned Bitbucket result set; commits are representative recent examples."
            ),
        },
        COMPACT_RESULT_TOKEN_BUDGET_KEY: compact_token_budget,
    }


def _compress_bitbucket_pull_requests(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_pull_requests = clamp_config_int(
        config,
        "max_pull_requests",
        default=100,
        minimum=10,
        maximum=300,
    )
    pull_requests = result.get("pull_requests") or []
    summarized_pull_requests: list[dict[str, Any]] = []
    for item in pull_requests[:max_pull_requests]:
        reviewers = item.get("reviewers") or []
        summarized_pull_requests.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "state": item.get("state"),
                "author": item.get("author"),
                "from_branch": item.get("from_branch"),
                "to_branch": item.get("to_branch"),
                "updated_date": item.get("updated_date"),
                "reviewer_count": len(reviewers),
                "approved_count": sum(1 for reviewer in reviewers if reviewer.get("approved")),
                "link": item.get("links"),
                # The model cites what it reads: the source fields survive compression.
                **source_subset(item),
            }
        )
    return {
        "project_key": result.get("project_key"),
        "repo_slug": result.get("repo_slug"),
        "state": result.get("state"),
        "pull_request_count": len(pull_requests),
        "pull_requests": summarized_pull_requests,
        "omitted_count": max(0, len(pull_requests) - len(summarized_pull_requests)),
    }


def _compress_workspace_git_commits(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    max_commits = clamp_config_int(config, "max_commits", default=150, minimum=10, maximum=500)
    commits = result.get("commits") or []
    authors: dict[str, int] = {}
    summarized_commits: list[dict[str, Any]] = []
    for item in commits:
        author_name = str(item.get("author_name") or "").strip()
        if author_name:
            authors[author_name] = authors.get(author_name, 0) + 1
    for item in commits[:max_commits]:
        summarized_commits.append(
            {
                "short_commit": item.get("short_commit"),
                "author_name": item.get("author_name"),
                "authored_at": item.get("authored_at"),
                "subject": item.get("subject"),
            }
        )
    return {
        "cwd": result.get("cwd"),
        "days": result.get("days"),
        "cutoff_utc": result.get("cutoff_utc"),
        "path": result.get("path"),
        "commit_count": result.get("commit_count"),
        "top_authors": sorted(authors.items(), key=lambda item: (-item[1], item[0]))[:10],
        "commits": summarized_commits,
        "omitted_count": max(0, len(commits) - len(summarized_commits)),
    }
