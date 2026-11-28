"""History of one file and its coupling to other files."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.git_intelligence.git_output import (
    RunGitFn,
    _changed_files_for_commit,
    git_command_failure,
    redacted_git_output,
)
from app.services.git_intelligence.helpers import (
    JIRA_TICKET_RE,
    find_repo_root,
    parse_commit_blocks,
    resolve_repo_relative_path,
)


async def _scan_file_commits(
    commits: list[dict[str, Any]],
    *,
    repo_root: Path,
    relative_path: str,
    cutoff: datetime,
    run_git: RunGitFn,
    db: AsyncSession | None,
    project_config: dict[str, Any] | None,
) -> tuple[Counter[str], Counter[str], set[str], int]:
    author_counter: Counter[str] = Counter()
    co_change_counter: Counter[str] = Counter()
    jira_tickets: set[str] = set()
    recent_commits = 0
    for commit in commits:
        commit["files"] = await _changed_files_for_commit(
            cwd=repo_root,
            sha=commit["sha"],
            run_git=run_git,
            db=db,
            project_config=project_config,
        )
        author_counter[commit["author_email"] or commit["author_name"]] += 1
        jira_tickets.update(JIRA_TICKET_RE.findall(commit["subject"]))
        try:
            authored_at = datetime.fromisoformat(commit["authored_at"].replace("Z", "+00:00"))
        except ValueError:
            authored_at = None
        if authored_at and authored_at >= cutoff:
            recent_commits += 1
        for changed in commit["files"]:
            if changed != relative_path:
                co_change_counter[changed] += 1

    return author_counter, co_change_counter, jira_tickets, recent_commits


def _risk_signal(recent_commits: int) -> str:
    risk_signal = "stable"
    if recent_commits >= 10:
        risk_signal = "high_volatility"
    elif recent_commits >= 4:
        risk_signal = "hot_file"
    return risk_signal


async def git_file_intelligence_impl(
    *,
    cwd: Path,
    file_path: str,
    days: int = 90,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    relative_path = resolve_repo_relative_path(repo_root, file_path)
    result = await run_git(
        [
            "log",
            "--date=iso-strict",
            "--pretty=format:COMMIT%x1f%H%x1f%ad%x1f%an%x1f%ae%x1f%s",
            "--name-only",
            "--",
            relative_path,
        ],
        cwd=repo_root,
        db=db,
        project_config=project_config,
    )
    if result["exit_code"] != 0:
        return git_command_failure("git_log_failed", result, repo_root)

    commits = parse_commit_blocks(redacted_git_output(result))
    cutoff = datetime.now(UTC) - timedelta(days=days)
    author_counter, co_change_counter, jira_tickets, recent_commits = await _scan_file_commits(
        commits,
        repo_root=repo_root,
        relative_path=relative_path,
        cutoff=cutoff,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )

    last_commit = commits[0] if commits else None
    risk_signal = _risk_signal(recent_commits)

    return {
        "file": relative_path,
        "repo_root": str(repo_root),
        "stats": {
            "total_commits": len(commits),
            "last_90_days": recent_commits,
            "unique_authors": len(author_counter),
            "primary_author": author_counter.most_common(1)[0][0] if author_counter else None,
            "last_modified": last_commit["authored_at"] if last_commit else None,
            "last_commit_message": last_commit["subject"] if last_commit else None,
        },
        "co_changed_files": [{"file": path, "count": count} for path, count in co_change_counter.most_common(5)],
        "jira_tickets": sorted(jira_tickets),
        "risk_signal": risk_signal,
    }


def _coupled_files(
    anchor_files: list[str],
    anchor_commit_count: Counter[str],
    co_change_count: dict[str, Counter[str]],
    threshold: float,
) -> list[dict[str, Any]]:
    coupled: list[dict[str, Any]] = []
    seen_files: set[str] = set(anchor_files)
    for anchor, counts in co_change_count.items():
        total = max(anchor_commit_count[anchor], 1)
        for file_path, count in counts.items():
            rate = count / total
            if rate < threshold:
                continue
            warning = "MISSING_FROM_CHANGE" if file_path not in seen_files else None
            coupled.append(
                {
                    "anchor": anchor,
                    "file": file_path,
                    "co_change_rate": round(rate, 2),
                    "warning": warning,
                }
            )
    return coupled


async def git_coupling_map_impl(
    *,
    cwd: Path,
    changed_files: list[str],
    threshold: float = 0.6,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    anchor_files = [resolve_repo_relative_path(repo_root, path) for path in changed_files if str(path).strip()]
    if not anchor_files:
        return {"error": "changed_files is required", "repo_root": str(repo_root)}

    anchor_commit_count: Counter[str] = Counter()
    co_change_count: dict[str, Counter[str]] = {anchor: Counter() for anchor in anchor_files}

    for anchor in anchor_files:
        result = await run_git(
            [
                "log",
                "--pretty=format:COMMIT%x1f%H",
                "--name-only",
                "--",
                anchor,
            ],
            cwd=repo_root,
            db=db,
            project_config=project_config,
        )
        if result["exit_code"] != 0:
            return git_command_failure("git_log_failed", result, repo_root)
        commits = parse_commit_blocks(redacted_git_output(result))
        for commit in commits:
            commit["files"] = await _changed_files_for_commit(
                cwd=repo_root,
                sha=commit["sha"],
                run_git=run_git,
                db=db,
                project_config=project_config,
            )
            anchor_commit_count[anchor] += 1
            for changed in commit["files"]:
                if changed != anchor:
                    co_change_count[anchor][changed] += 1

    coupled = _coupled_files(anchor_files, anchor_commit_count, co_change_count, threshold)

    return {
        "repo_root": str(repo_root),
        "anchor_files": anchor_files,
        "coupled_files": sorted(coupled, key=lambda item: item["co_change_rate"], reverse=True),
        "risk": "incomplete_change" if any(item.get("warning") for item in coupled) else "low",
    }

