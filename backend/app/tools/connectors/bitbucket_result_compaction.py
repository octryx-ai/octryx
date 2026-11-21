"""Bitbucket tool result compaction for model context (registered by ``atlassian_result_compaction``)."""

from __future__ import annotations

from typing import Any

from app.services.answer_evidence.fields import source_subset

from ...agent.core.runtime.trace_runtime import compact_trace_value
from ...agent.engine.messages._engine_message_helpers import _path_tail, _truncate_for_model
from .atlassian_result_compaction import _compact_count_map, _increment_count


def compact_bitbucket_pull_request_result(result: dict[str, Any]) -> dict[str, Any]:
    values = result.get("values") if isinstance(result.get("values"), list) else None
    source = values[0] if values else result
    if not isinstance(source, dict):
        source = result
    reviewers = []
    for item in (source.get("reviewers") or [])[:12]:
        if not isinstance(item, dict):
            continue
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        reviewers.append(
            {
                "name": user.get("displayName") or user.get("name") or item.get("displayName") or item.get("name"),
                "status": item.get("status"),
                "approved": item.get("approved"),
            }
        )
    links = source.get("links") if isinstance(source.get("links"), dict) else {}
    self_links = links.get("self") if isinstance(links.get("self"), list) else []
    return {
        "id": source.get("id") or result.get("id"),
        "title": _truncate_for_model(source.get("title") or result.get("title") or "", 220),
        **(source_subset(source) or source_subset(result)),
        "state": source.get("state") or result.get("state"),
        "url": source.get("url")
        or result.get("url")
        or next((item.get("href") for item in self_links if isinstance(item, dict) and item.get("href")), None),
        "from_ref": compact_trace_value(source.get("fromRef") or source.get("from_ref") or result.get("fromRef")),
        "to_ref": compact_trace_value(source.get("toRef") or source.get("to_ref") or result.get("toRef")),
        "author": compact_trace_value(source.get("author") or result.get("author")),
        "reviewers": reviewers,
        "updated_date": source.get("updatedDate") or source.get("updated_date") or result.get("updatedDate"),
        "answer_guidance": {
            "raw_payload_available_as_artifact": True,
            "declined_pull_requests_are_not_implementation_success": True,
        },
    }


def compact_prepare_repository_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_key": result.get("project_key"),
        "repo_slug": result.get("repo_slug"),
        "repository_url": result.get("repository_url") or result.get("url") or result.get("web_url"),
        "branch_name": result.get("branch_name"),
        "base_branch": result.get("base_branch") or result.get("default_branch"),
        "relative_path": result.get("relative_path") or _path_tail(result.get("local_path")),
        "local_path_tail": _path_tail(result.get("local_path")),
        "status": result.get("status"),
        "created_branch": result.get("created_branch"),
        "already_exists": result.get("already_exists"),
        "answer_guidance": {
            "use_relative_path_for_workspace_tools": True,
            "absolute_paths_are_runtime_local": True,
            "raw_payload_available_as_artifact": True,
        },
    }


def _recent_commit_item(commit: dict[str, Any]) -> dict[str, Any]:
    return {
        "repository_label": commit.get("repository_label")
        or f"{commit.get('project_key')}/{commit.get('repo_slug')}",
        "project_key": commit.get("project_key"),
        "repo_slug": commit.get("repo_slug"),
        "display_id": commit.get("display_id"),
        "message": _truncate_for_model(commit.get("message") or "", 180),
        "author_name": commit.get("author_name"),
        "author_timestamp": commit.get("author_timestamp"),
        "branches": (commit.get("branches") or [])[:5],
        **source_subset(commit),
    }


def _repository_summary(repo: dict[str, Any]) -> dict[str, Any]:
    commits = []
    repo_branch_counts: dict[str, int] = {}
    for commit in (repo.get("commits") or [])[:3]:
        branches = [str(branch).strip() for branch in (commit.get("branches") or []) if str(branch).strip()]
        for branch in branches:
            repo_branch_counts[branch] = repo_branch_counts.get(branch, 0) + 1
        commits.append(
            {
                "display_id": commit.get("display_id"),
                "message": _truncate_for_model(commit.get("message") or "", 180),
                "author_name": commit.get("author_name"),
                "author_timestamp": commit.get("author_timestamp"),
                "branches": branches[:5],
                **source_subset(commit),
            }
        )
    return {
        "label": repo.get("label") or f"{repo.get('project_key')}/{repo.get('repo_slug')}",
        "project_key": repo.get("project_key"),
        "repo_slug": repo.get("repo_slug"),
        "commit_count": repo.get("commit_count"),
        "branches_scanned": (repo.get("branches_scanned") or [])[:12],
        "branch_mode": repo.get("branch_mode"),
        "top_branches": sorted(repo_branch_counts.items(), key=lambda item: (-item[1], item[0]))[:5],
        "recent_commits": commits,
    }


def _commit_counts(
    repositories: list[dict[str, Any]], commits: list[dict[str, Any]]
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    repository_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    branch_counts: dict[str, int] = {}
    for repo_item in repositories:
        label = str(repo_item.get("label") or f"{repo_item.get('project_key')}/{repo_item.get('repo_slug')}").strip()
        if label:
            repository_counts[label] = int(repo_item.get("commit_count") or 0)
    for commit_item in commits:
        _increment_count(author_counts, commit_item.get("author_name"))
        for branch in commit_item.get("branches") or []:
            _increment_count(branch_counts, branch)
    return repository_counts, author_counts, branch_counts


def compact_recent_bitbucket_commits_result(result: dict[str, Any]) -> dict[str, Any]:
    all_repositories = result.get("repositories") or []
    all_commits = result.get("commits") or []
    repository_counts, author_counts, branch_counts = _commit_counts(all_repositories, all_commits)
    sorted_repositories = sorted(
        all_repositories,
        key=lambda item: (-(int(item.get("commit_count") or 0)), str(item.get("label") or "")),
    )
    repos = [_repository_summary(repo) for repo in sorted_repositories[:10]]
    return {
        "days": result.get("days"),
        "cutoff_utc": result.get("cutoff_utc"),
        "branch_mode": result.get("branch_mode"),
        "author_filter": result.get("author_filter"),
        "total_commit_count": result.get("total_commit_count"),
        "repository_count": len(all_repositories),
        "returned_repository_count": len(repos),
        "omitted_repository_count": max(0, len(all_repositories) - len(repos)),
        "returned_global_commit_count": min(len(all_commits), 12),
        "omitted_global_commit_count": max(0, len(all_commits) - 12),
        "repository_commit_counts": _compact_count_map(repository_counts, limit=12),
        "author_counts": _compact_count_map(author_counts, limit=10),
        "branch_counts": _compact_count_map(branch_counts, limit=10),
        "repositories": repos,
        "recent_commits": [_recent_commit_item(commit) for commit in all_commits[:12]],
        "answer_guidance": {
            "use_counts_before_examples": True,
            "raw_payload_available_as_artifact": True,
        },
    }
