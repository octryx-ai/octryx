from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.git_intelligence.analysis import RunGitFn, git_coupling_map_impl
from app.services.git_intelligence.change_summary import git_change_summary_impl
from app.services.git_intelligence.diagnostics import git_hotspot_analysis_impl
from app.services.git_intelligence.helpers import find_repo_root, resolve_repo_relative_path


async def git_conflict_predictor_impl(
    *,
    cwd: Path,
    planned_files: list[str],
    open_pull_requests: list[dict[str, Any]] | None = None,
    threshold: float = 0.6,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    normalized_files = [resolve_repo_relative_path(repo_root, path) for path in planned_files if str(path).strip()]
    if not normalized_files:
        return {"error": "planned_files is required", "repo_root": str(repo_root)}

    coupling = await git_coupling_map_impl(
        cwd=repo_root,
        changed_files=normalized_files,
        threshold=threshold,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    overlapping_prs: list[dict[str, Any]] = []
    overlap_files: set[str] = set()
    for pr in open_pull_requests or []:
        pr_files = {str(item).strip() for item in (pr.get("files") or []) if str(item).strip()}
        overlap = sorted(pr_files.intersection(normalized_files))
        if not overlap:
            continue
        overlap_files.update(overlap)
        overlapping_prs.append(
            {
                "id": pr.get("id"),
                "title": pr.get("title"),
                "author": pr.get("author"),
                "status": pr.get("status") or pr.get("state"),
                "overlap_files": overlap,
            }
        )

    missing_companions = [
        item["file"] for item in coupling.get("coupled_files", []) if item.get("warning") == "MISSING_FROM_CHANGE"
    ]
    risk = "low"
    if overlapping_prs:
        risk = "high"
    elif missing_companions:
        risk = "medium"
    return {
        "repo_root": str(repo_root),
        "planned_files": normalized_files,
        "coupling": coupling,
        "overlapping_pull_requests": overlapping_prs,
        "missing_companion_files": sorted(set(missing_companions)),
        "risk": risk,
    }


async def git_pr_context_impl(
    *,
    cwd: Path,
    changed_files: list[str],
    pr: dict[str, Any] | None = None,
    days: int = 90,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    normalized_files = [resolve_repo_relative_path(repo_root, path) for path in changed_files if str(path).strip()]
    if not normalized_files:
        return {"error": "changed_files is required", "repo_root": str(repo_root)}

    history = await git_change_summary_impl(
        cwd=repo_root,
        paths=normalized_files,
        days=days,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    coupling = await git_coupling_map_impl(
        cwd=repo_root,
        changed_files=normalized_files,
        threshold=0.55,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    hotspots = await git_hotspot_analysis_impl(
        cwd=repo_root,
        days=days,
        top_n=20,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    relevant_hotspots = [item for item in hotspots.get("hotspots", []) if item.get("file") in normalized_files][:10]
    related_jira = sorted(
        {
            item["jira"]
            for bucket in ("bug_fixes", "refactors", "features")
            for item in history.get("summary", {}).get(bucket, [])
            if item.get("jira")
        }
    )
    return {
        "repo_root": str(repo_root),
        "pull_request": pr or None,
        "changed_files": normalized_files,
        "history_summary": history,
        "coupling": coupling,
        "hotspots": relevant_hotspots,
        "related_jira": related_jira,
    }


def _history_knowledge(
    summary: dict[str, Any], extract_types: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    decisions = []
    known_bugs = []
    api_contracts = []
    for item in summary.get("summary", {}).get("features", []):
        lowered = item["message"].lower()
        if "decision" in lowered or lowered.startswith(("feat", "refactor", "chore")):
            decisions.append(
                {
                    "date": item["date"],
                    "decision": item["message"],
                    "reason": f"Extracted from commit '{item['message']}'",
                    "jira": item.get("jira"),
                }
            )
    for item in summary.get("summary", {}).get("bug_fixes", []):
        known_bugs.append(
            {
                "pattern": item["message"],
                "fixed_in": item["date"],
                "watch_for": item.get("jira"),
            }
        )
    if "api_contracts" in extract_types:
        for item in summary.get("summary", {}).get("features", []):
            lowered = item["message"].lower()
            if "api" in lowered or "contract" in lowered:
                api_contracts.append(
                    {
                        "date": item["date"],
                        "summary": item["message"],
                        "files": item.get("files", []),
                    }
                )
    return decisions, known_bugs, api_contracts


async def git_knowledge_extract_impl(
    *,
    cwd: Path,
    scope: str = ".",
    extract_types: list[str] | None = None,
    days: int = 90,
    run_git: RunGitFn,
    db: AsyncSession | None = None,
    project_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extract_types = extract_types or ["decisions", "bug_patterns", "api_contracts"]
    summary = await git_change_summary_impl(
        cwd=cwd,
        paths=[scope],
        days=days,
        run_git=run_git,
        db=db,
        project_config=project_config,
    )
    if summary.get("error"):
        return summary

    decisions, known_bugs, api_contracts = _history_knowledge(summary, extract_types)

    scope_slug = re.sub(r"[^a-zA-Z0-9]+", "_", scope).strip("_") or "repo"
    return {
        "category": "codebase_history",
        "key": f"{scope_slug}_history",
        "value": {
            "scope": scope,
            "decisions": decisions[:20],
            "known_bugs": known_bugs[:20],
            "api_contracts": api_contracts[:20],
            "summary": summary,
        },
    }
