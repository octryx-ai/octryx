from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from ..git_intelligence.helpers import find_repo_root
from ..git_intelligence_service import _run_git, git_change_summary

SECRET_PATTERN = re.compile(
    r"(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    re.IGNORECASE,
)
DEBUG_PATTERN = re.compile(r"\b(console\.log|print\(|pdb\.set_trace|debugger)\b")
TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX)\b")


def _normalize_changed_files(changed_files: list[str] | None) -> list[str]:
    return [str(Path(path)).strip().strip("/") for path in (changed_files or []) if str(path).strip()]


def _is_test_path(path: str) -> bool:
    lowered = path.lower()
    return (
        "/tests/" in lowered
        or lowered.startswith("tests/")
        or lowered.endswith("_test.py")
        or lowered.endswith(".spec.ts")
        or lowered.endswith(".test.ts")
        or lowered.endswith(".spec.tsx")
        or lowered.endswith(".test.tsx")
        or lowered.endswith("_test.go")
    )


def _is_code_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt"))


async def _git_diff_name_only(repo_root: Path) -> list[str]:
    result = await _run_git(["diff", "--name-only", "HEAD"], cwd=repo_root)
    tracked = (
        [line.strip() for line in result["stdout"].splitlines() if line.strip()] if result["exit_code"] == 0 else []
    )
    untracked_result = await _run_git(["ls-files", "--others", "--exclude-standard"], cwd=repo_root)
    untracked = (
        [line.strip() for line in untracked_result["stdout"].splitlines() if line.strip()]
        if untracked_result["exit_code"] == 0
        else []
    )
    seen: set[str] = set()
    return [path for path in tracked + untracked if not (path in seen or seen.add(path))]


async def _build_untracked_diff_text(repo_root: Path, paths: list[str]) -> str:
    diff_blocks: list[str] = []
    for relative_path in paths:
        file_path = repo_root / relative_path
        if not file_path.is_file():
            continue
        try:
            content = await asyncio.to_thread(file_path.read_text, encoding="utf-8", errors="replace")
        except Exception:
            continue
        added_lines = "\n".join(f"+{line}" for line in content.splitlines())
        if content and not added_lines.endswith("\n"):
            added_lines = f"{added_lines}\n"
        diff_blocks.append(
            "\n".join(
                [
                    f"diff --git a/{relative_path} b/{relative_path}",
                    "new file mode 100644",
                    "--- /dev/null",
                    f"+++ b/{relative_path}",
                    "@@ -0,0 +1 @@",
                    added_lines.rstrip("\n"),
                ]
            ).rstrip()
        )
    return "\n\n".join(block for block in diff_blocks if block).strip()


async def _git_diff_text(repo_root: Path) -> str:
    result = await _run_git(["diff", "--unified=0", "HEAD"], cwd=repo_root)
    tracked_diff = result["stdout"] if result["exit_code"] == 0 else ""
    untracked_result = await _run_git(["ls-files", "--others", "--exclude-standard"], cwd=repo_root)
    untracked_files = (
        [line.strip() for line in untracked_result["stdout"].splitlines() if line.strip()]
        if untracked_result["exit_code"] == 0
        else []
    )
    untracked_diff = await _build_untracked_diff_text(repo_root, untracked_files)
    return "\n\n".join(part for part in [tracked_diff.strip(), untracked_diff.strip()] if part).strip()


async def self_review_workspace_diff(
    *,
    cwd: Path,
    changed_files: list[str] | None = None,
    diff_text: str | None = None,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    normalized_files = _normalize_changed_files(changed_files)
    if not normalized_files:
        normalized_files = await _git_diff_name_only(repo_root)
    if diff_text is None:
        diff_text = await _git_diff_text(repo_root)

    findings: list[dict[str, Any]] = []
    code_files = [path for path in normalized_files if _is_code_path(path)]
    test_files = [path for path in normalized_files if _is_test_path(path)]

    if code_files and not test_files:
        findings.append(
            {
                "severity": "medium",
                "type": "missing_tests",
                "title": "Code changed without visible test updates",
                "detail": (
                    "Code files changed but no test files appear in the diff. "
                    "Add or update focused regression tests before review."
                ),
                "files": code_files[:10],
            }
        )
    if SECRET_PATTERN.search(diff_text or ""):
        findings.append(
            {
                "severity": "high",
                "type": "hardcoded_secret",
                "title": "Potential hardcoded secret in diff",
                "detail": (
                    "The diff appears to introduce a token, password, API key, "
                    "or secret literal. Remove it before opening a PR."
                ),
                "files": normalized_files[:10],
            }
        )
    if DEBUG_PATTERN.search(diff_text or ""):
        findings.append(
            {
                "severity": "medium",
                "type": "debug_artifact",
                "title": "Debug artifact present",
                "detail": (
                    "The diff contains console logging, print debugging, or "
                    "debugger hooks that should usually be removed before review."
                ),
                "files": normalized_files[:10],
            }
        )
    if TODO_PATTERN.search(diff_text or ""):
        findings.append(
            {
                "severity": "low",
                "type": "todo_marker",
                "title": "TODO/FIXME marker introduced",
                "detail": (
                    "The diff contains TODO/FIXME markers. Either resolve them "
                    "now or justify them explicitly in the PR."
                ),
                "files": normalized_files[:10],
            }
        )

    risk_level = "low"
    if any(item["severity"] == "high" for item in findings):
        risk_level = "high"
    elif findings:
        risk_level = "medium"

    return {
        "repo_root": str(repo_root),
        "changed_files": normalized_files,
        "finding_count": len(findings),
        "risk_level": risk_level,
        "ready_for_pr": len(findings) == 0,
        "findings": findings,
    }


async def build_pull_request_description(
    *,
    cwd: Path,
    summary: str | None = None,
    changed_files: list[str] | None = None,
    test_results: dict[str, Any] | None = None,
    lint_results: dict[str, Any] | None = None,
    risk_notes: list[str] | None = None,
    template: dict[str, Any] | None = None,
    days: int = 30,
) -> dict[str, Any]:
    repo_root = find_repo_root(cwd)
    normalized_files = _normalize_changed_files(changed_files)
    if not normalized_files:
        normalized_files = await _git_diff_name_only(repo_root)

    history = await git_change_summary(cwd=repo_root, paths=normalized_files, days=days)
    template = template or {}
    sections = template.get("sections") or ["summary", "changes", "test_plan", "risk", "checklist"]
    checklist = template.get("checklist") or [
        "Tests written and passing",
        "Linter/formatter clean",
        "No hardcoded secrets",
        "Documentation updated if needed",
        "Breaking changes noted",
    ]

    change_lines = [f"- `{path}`" for path in normalized_files[:20]] or ["- No changed files detected"]
    test_plan_lines: list[str] = []
    if test_results:
        test_plan_lines.append(f"- Test suite: {'green' if test_results.get('all_green') else 'attention needed'}")
        if test_results.get("command"):
            test_plan_lines.append(f"- Command: `{test_results['command']}`")
        if test_results.get("coverage_pct") is not None:
            test_plan_lines.append(f"- Coverage: {test_results['coverage_pct']}%")
    if lint_results:
        test_plan_lines.append(f"- Lint/format: {'clean' if lint_results.get('all_clean') else 'issues found'}")
    if not test_plan_lines:
        test_plan_lines.append("- Document the exact commands used for validation before opening the PR.")

    risk_lines = [f"- {note}" for note in (risk_notes or []) if str(note).strip()]
    if not risk_lines:
        trend = history.get("trend")
        risk_lines.append(f"- Historical trend for touched files: {trend or 'unknown'}")

    section_text: dict[str, str] = {
        "summary": summary or "Describe the problem and the intended outcome.",
        "changes": "\n".join(change_lines),
        "test_plan": "\n".join(test_plan_lines),
        "risk": "\n".join(risk_lines),
        "checklist": "\n".join(f"- [ ] {item}" for item in checklist),
    }
    markdown = "\n\n".join(
        f"## {section.replace('_', ' ').title()}\n{section_text.get(section, '')}".rstrip() for section in sections
    ).strip()
    return {
        "repo_root": str(repo_root),
        "changed_files": normalized_files,
        "history_summary": history,
        "markdown": markdown,
        "sections": sections,
        "checklist": checklist,
    }


__all__ = [
    "build_pull_request_description",
    "self_review_workspace_diff",
]
