"""Where to look closely, and why."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any

from ..workflow_runs import safe_git

DAYS, CHURN_MIN, LARGE_LINES, MAX_HOTSPOTS = 90, 3, 80, 5
DEFAULT_SENSITIVE = ("auth", "login", "password", "token", "secret", "crypto", "security", "permission", "payment",
                     "billing", "migration", "sql")
_BUGFIX = re.compile(r"\b(fix|fixes|fixed|bug|hotfix|regression)\b", re.IGNORECASE)
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Hotspot:
    path: str
    line: int
    score: float
    reasons: tuple[str, ...]
    lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "score": round(self.score, 1), "reasons": list(self.reasons)}


def sensitive(path: str, extra: tuple[str, ...] = ()) -> str:
    lowered = path.lower()
    word = next((word for word in DEFAULT_SENSITIVE if re.search(rf"(^|[/_.\-]){word}", lowered)), "")
    if word:
        return word
    return next((glob for glob in extra if fnmatch.fnmatch(path, glob)), "")


def score(path: str, *, commits: int, bug_fixes: int, area: str, lines: int) -> tuple[float, tuple[str, ...]]:
    reasons, points = [], 0.0
    if area:
        reasons.append(f"touches a sensitive area ({area})")
        points += 4
    if bug_fixes:
        reasons.append(f"{bug_fixes} bug fix(es) in the last {DAYS} days")
        points += 3 * bug_fixes
    if commits >= CHURN_MIN:
        reasons.append(f"changed in {commits} commits in the last {DAYS} days")
        points += commits
    if lines >= LARGE_LINES:
        reasons.append(f"a large change ({lines} lines)")
        points += lines / 50
    return points, tuple(reasons)


async def _history(root: str, head: str, path: str) -> tuple[int, int]:
    code, out, _err = await safe_git.git(root, "log", f"--since={DAYS}.days", "--format=%s", head, "--", path)
    subjects = [line for line in out.splitlines() if line.strip()] if code == 0 else []
    return len(subjects), sum(1 for subject in subjects if _BUGFIX.search(subject))


async def _first_line(root: str, base: str, head: str, path: str) -> int:
    code, out, _err = await safe_git.git(root, *safe_git.DIFF, "-U0", base, head, "--", path)
    match = _HUNK.search(out) if code == 0 else None
    return max(1, int(match.group(1))) if match else 1


async def hotspots(root: str, base: str, head: str, files: list[dict[str, Any]],
                   extra: tuple[str, ...] = ()) -> list[Hotspot]:
    found = []
    for item in files:
        if item.get("kind") != "careful" or not int(item.get("lines") or 0):
            continue  # an empty or unchanged file is no hotspot (e.g. an empty __init__.py)
        path = str(item.get("path"))
        commits, fixes = await _history(root, base or head, path)
        points, reasons = score(path, commits=commits, bug_fixes=fixes, area=sensitive(path, extra),
                                lines=int(item.get("lines") or 0))
        if reasons:
            found.append(Hotspot(path, await _first_line(root, base, head, path), points, reasons,
                                 int(item.get("lines") or 0)))
    # The same score: more reasons first, then the larger change.
    return sorted(found, key=lambda spot: (-spot.score, -len(spot.reasons), -spot.lines, spot.path))[:MAX_HOTSPOTS]


def section(spots: list[Hotspot]) -> str:
    return "\n".join(f"{spot.path}:{spot.line}: {'; '.join(spot.reasons)}" for spot in spots)


__all__ = ["DEFAULT_SENSITIVE", "Hotspot", "hotspots", "score", "section", "sensitive"]
