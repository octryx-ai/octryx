from __future__ import annotations

import re
from pathlib import Path
from typing import Any

JIRA_TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def find_repo_root(cwd: Path) -> Path:
    for candidate in [cwd, *cwd.parents]:
        if (candidate / ".git").exists():
            return candidate
    return cwd


def resolve_repo_relative_path(repo_root: Path, file_path: str) -> str:
    candidate = Path(file_path)
    resolved = candidate if candidate.is_absolute() else (repo_root / candidate)
    resolved = resolved.resolve()
    try:
        return str(resolved.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(candidate).strip().strip("/")


def find_symbol_range(file_path: Path, symbol: str) -> tuple[int, int] | None:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    patterns = [
        re.compile(rf"^\s*(?:async\s+def|def|class)\s+{re.escape(symbol)}\b"),
        re.compile(rf"^\s*func\s+(?:\([^)]*\)\s*)?{re.escape(symbol)}\b"),
        re.compile(rf"^\s*(?:export\s+)?(?:async\s+)?function\s+{re.escape(symbol)}\b"),
        re.compile(rf"^\s*(?:export\s+)?(?:const|let|var)\s+{re.escape(symbol)}\s*=\s*(?:async\s*)?\("),
    ]
    block_start: int | None = None
    base_indent = 0
    for idx, line in enumerate(lines, start=1):
        if any(pattern.search(line) for pattern in patterns):
            block_start = idx
            base_indent = len(line) - len(line.lstrip(" \t"))
            break
    if block_start is None:
        return None

    block_end = len(lines)
    boundary_patterns = [
        re.compile(r"^\s*(?:async\s+def|def|class)\s+[A-Za-z_]\w*\b"),
        re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?[A-Za-z_]\w*\b"),
        re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+[A-Za-z_]\w*\b"),
        re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_]\w*\s*=\s*(?:async\s*)?\("),
    ]
    for idx in range(block_start + 1, len(lines) + 1):
        line = lines[idx - 1]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" \t"))
        if indent <= base_indent and any(pattern.search(line) for pattern in boundary_patterns):
            block_end = idx - 1
            break
    return block_start, max(block_start, block_end)


def parse_commit_blocks(text: str) -> list[dict[str, Any]]:
    commits: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if line.startswith("COMMIT\x1f"):
            if current:
                commits.append(current)
            _, sha, authored_at, author_name, author_email, subject = (
                line.split("\x1f", 5) + ["", "", "", "", "", ""]
            )[:6]
            current = {
                "sha": sha,
                "authored_at": authored_at,
                "author_name": author_name,
                "author_email": author_email,
                "subject": subject,
                "files": [],
            }
        elif current is not None and line.strip():
            current["files"].append(line.strip())
    if current:
        commits.append(current)
    return commits
