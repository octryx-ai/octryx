"""What changed in a scope lately: commits sorted into fixes, refactors and features, and the trend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.git_intelligence.git_output import RunGitFn, git_command_failure, redacted_git_output
from app.services.git_intelligence.helpers import JIRA_TICKET_RE, find_repo_root, parse_commit_blocks


def _classify_commits(
    commits: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    """Commits sorted into bug fixes, refactors and features by subject, plus the authors seen."""
    bug_fixes = []
    refactors = []
    features = []
    active_authors: set[str] = set()
    for commit in commits:
        active_authors.add(commit["author_name"] or commit["author_email"])
        summary_item = {
            "date": commit["authored_at"],
            "message": commit["subject"],
            "files": commit["files"][:10],
            "jira": next(iter(JIRA_TICKET_RE.findall(commit["subject"])), None),
        }
        subject = commit["subject"].lower()
        if subject.startswith("fix") or "bug" in subject:
            bug_fixes.append(summary_item)
        elif subject.startswith("refactor"):
            refactors.append(summary_item)
        else:
            features.append(summary_item)
    return bug_fixes, refactors, features, active_authors


async def git_change_summary_impl(
    *,
    cwd: Path,
    paths: list[str],
    days: int = 30,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    cutoff = datetime.now(UTC) - timedelta(days=max(1, days))
    args = [
        "log",
        f"--since={cutoff.isoformat()}",
        "--date=iso-strict",
        "--pretty=format:COMMIT%x1f%H%x1f%ad%x1f%an%x1f%ae%x1f%s",
        "--name-only",
    ]
    if paths:
        args.extend(["--", *paths])
    result = await run_git(args, cwd=repo_root, db=db, project_config=project_config)
    if result["exit_code"] != 0:
        return git_command_failure("git_log_failed", result, repo_root)

    commits = parse_commit_blocks(redacted_git_output(result))
    bug_fixes, refactors, features, active_authors = _classify_commits(commits)

    trend = "stable"
    if len(bug_fixes) >= 5:
        trend = "unstable"
    elif len(refactors) + len(features) >= 8:
        trend = "active"
    return {
        "period": f"last_{days}_days",
        "scope": paths,
        "summary": {
            "total_commits": len(commits),
            "bug_fixes": bug_fixes[:10],
            "refactors": refactors[:10],
            "features": features[:10],
            "active_authors": sorted(active_authors),
        },
        "trend": trend,
    }
