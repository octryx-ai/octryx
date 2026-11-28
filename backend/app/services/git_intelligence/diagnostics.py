from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.git_intelligence.analysis import RunGitFn, git_command_failure, redacted_git_output
from app.services.git_intelligence.helpers import (
    JIRA_TICKET_RE,
    find_repo_root,
    find_symbol_range,
    resolve_repo_relative_path,
)


async def _commit_subjects(
    *,
    cwd: Path,
    commit_ids: list[str],
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, str]:
    subjects: dict[str, str] = {}
    for commit_id in commit_ids:
        result = await run_git(["show", "-s", "--format=%s", commit_id], cwd=cwd, db=db, project_config=project_config)
        if result["exit_code"] != 0:
            continue
        # The commit subject is returned as blame evidence: kept, through the redactor.
        subjects[commit_id] = redacted_git_output(result).strip()
    return subjects


async def git_hotspot_analysis_impl(
    *,
    cwd: Path,
    days: int = 90,
    top_n: int = 15,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    cutoff = datetime.now(UTC) - timedelta(days=max(1, days))
    result = await run_git(
        ["log", f"--since={cutoff.isoformat()}", "--name-only", "--pretty=format:COMMIT"],
        cwd=repo_root,
        db=db,
        project_config=project_config,
    )
    if result["exit_code"] != 0:
        return git_command_failure("git_log_failed", result, repo_root)

    frequency: Counter[str] = Counter()
    for line in redacted_git_output(result).splitlines():
        line = line.strip()
        if not line or line == "COMMIT":
            continue
        frequency[line] += 1

    hotspots = []
    for file_path, change_frequency in frequency.most_common(top_n):
        full_path = (repo_root / file_path).resolve()
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        complexity_score = min(
            100,
            text.count("if ") + text.count("for ") + text.count("while ") + text.count("def ") + text.count("class "),
        )
        risk_score = round((change_frequency * max(complexity_score, 1)) / 100, 1)
        hotspots.append(
            {
                "file": file_path,
                "change_frequency": change_frequency,
                "complexity_score": complexity_score,
                "risk_score": risk_score,
                "recommendation": "refactor_candidate" if risk_score >= 5 else "observe",
            }
        )

    return {
        "repo_root": str(repo_root),
        "hotspots": hotspots,
        "stable_modules": [item["file"] for item in hotspots if item["risk_score"] <= 1.5][:5],
    }


def _parse_blame(output: str) -> tuple[Counter[str], Counter[str], dict[str, str]]:
    commit_counts: Counter[str] = Counter()
    author_counts: Counter[str] = Counter()
    commit_authors: dict[str, str] = {}
    last_commit: str | None = None
    for line in output.splitlines():
        if re.fullmatch(r"[0-9a-f]{8,40} \d+ \d+ \d+", line):
            commit_id = line.split()[0]
            commit_counts[commit_id] += 1
            last_commit = commit_id
            continue
        if line.startswith("author "):
            author = line.removeprefix("author ").strip()
            if last_commit:
                commit_authors[last_commit] = author
                author_counts[author] += 1
    return commit_counts, author_counts, commit_authors


def _ownership(
    author_counts: Counter[str], commit_counts: Counter[str], commit_subjects: dict[str, str], line_total: int
) -> dict[str, Any]:
    return {
        "owners": [
            {
                "author": author,
                "line_count": count,
                "share": round(count / line_total, 2),
            }
            for author, count in author_counts.most_common()
        ],
        "commit_spread": [
            {
                "commit": commit_id,
                "line_count": count,
                "message": commit_subjects.get(commit_id),
            }
            for commit_id, count in commit_counts.most_common()
        ],
    }


async def git_function_blame_impl(
    *,
    cwd: Path,
    file_path: str,
    symbol: str,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    relative_path = resolve_repo_relative_path(repo_root, file_path)
    full_path = (repo_root / relative_path).resolve()
    symbol_range = find_symbol_range(full_path, symbol)
    if symbol_range is None:
        return {
            "error": f"symbol '{symbol}' not found",
            "file": relative_path,
            "repo_root": str(repo_root),
        }

    start_line, end_line = symbol_range
    result = await run_git(
        ["blame", "--line-porcelain", f"-L{start_line},{end_line}", "--", relative_path],
        cwd=repo_root,
        db=db,
        project_config=project_config,
    )
    if result["exit_code"] != 0:
        return git_command_failure("git_blame_failed", result, repo_root)

    commit_counts, author_counts, commit_authors = _parse_blame(redacted_git_output(result))

    commit_subjects = await _commit_subjects(
        cwd=repo_root,
        commit_ids=list(commit_counts),
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    jira_tickets = sorted(
        {ticket for subject in commit_subjects.values() for ticket in JIRA_TICKET_RE.findall(subject)}
    )
    primary_commit = commit_counts.most_common(1)[0][0] if commit_counts else None
    primary_author = commit_authors.get(
        primary_commit or "", author_counts.most_common(1)[0][0] if author_counts else None
    )
    return {
        "repo_root": str(repo_root),
        "file": relative_path,
        "symbol": symbol,
        "line_range": {"start": start_line, "end": end_line},
        "primary_author": primary_author,
        **_ownership(author_counts, commit_counts, commit_subjects, max(end_line - start_line + 1, 1)),
        "jira_tickets": jira_tickets,
    }
