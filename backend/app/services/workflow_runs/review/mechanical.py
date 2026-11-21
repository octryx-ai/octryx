"""Whether a file's change is purely mechanical, so a review may leave it out of the diff it shows (a stage of the
PR review bot; the rules are strict because this hides code from the reviewer):

- **renamed** only at 100 % similarity (git ``R100``);
- **line endings only** (``git diff --ignore-cr-at-eol`` empty), in any text file;
- **whitespace only** (``-w``) only where whitespace carries no meaning (``WHITESPACE_FREE``: JSON, the C family,
  JavaScript/TypeScript, Dart, Java, Kotlin, Go, ...); never Python, YAML, Makefiles, Markdown or shell;
- **Python** only with the same syntax tree, and never when a pragma (``# type: ignore``, ``# noqa``,
  ``# pragma: ...``) or the encoding line changed: the reviewer sees those.

``mechanical_reason`` is asked by the bot (against the head commit) and again by the review's evidence (against the
staged copy) for every path a context key claims: what the check does not confirm stays in the diff.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from .. import safe_git

WHITESPACE_FREE = frozenset({
    ".json", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".dart", ".java", ".kt", ".kts", ".go", ".c", ".h",
    ".cc", ".cpp", ".hpp", ".cs", ".swift", ".rs", ".scala", ".php", ".css", ".scss"})
_PRAGMA = re.compile(r"#\s*(?:type:\s*ignore|noqa|pragma\b)|^#.*coding[:=]", re.IGNORECASE)


def same_python_tree(before: str, after: str) -> bool:
    """The same syntax tree and the same pragma and encoding lines. Pure."""
    def pragmas(text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if _PRAGMA.search(line)]

    if pragmas(before) != pragmas(after):
        return False
    try:
        return ast.dump(ast.parse(before)) == ast.dump(ast.parse(after))
    except (SyntaxError, ValueError):
        return False


async def mechanical_reason(root: str | Path, base: str, path: str, *, old: str = "", head: str = "") -> str:
    """Why the change of ``path`` (renamed from ``old``) between ``base`` and ``head`` (a commit; ``''``: the staged
    copy) is mechanical; ``''`` when it is not, or when it cannot be shown."""
    target = ["--cached"] if not head else [head]
    if old:
        code, out, _err = await safe_git.git(root, *safe_git.DIFF, "--name-status", "-M100%", base, *target, "--",
                                             old, path)
        rows = [row.split("\t") for row in out.splitlines()] if code == 0 else []
        renamed = any(len(row) == 3 and row[0] == "R100" and row[1] == old and row[2] == path for row in rows)
        return f"renamed from {old} without a change" if renamed else ""
    code, out, _err = await safe_git.git(root, *safe_git.DIFF, "--ignore-cr-at-eol", base, *target, "--", path)
    if code != 0:
        return ""
    if not out.strip():
        return "line endings only"
    if Path(path).suffix.lower() in WHITESPACE_FREE:
        code, out, _err = await safe_git.git(root, *safe_git.DIFF, "-w", "--ignore-cr-at-eol", "--ignore-blank-lines",
                                             base, *target, "--", path)
        return "whitespace only" if code == 0 and not out.strip() else ""
    if path.endswith(".py"):
        before = await safe_git.git(root, "show", f"{base}:{path}")
        after = await safe_git.git(root, "show", f"{head}:{path}" if head else f":{path}")
        if before[0] == 0 and after[0] == 0 and same_python_tree(before[1], after[1]):
            return "same Python syntax tree (formatting or comments only)"
    return ""


async def verified_mechanical(run: Any, root: Path, base: str) -> list[tuple[str, str]]:
    """The paths a step claims as mechanical (``review_summarized_paths``, the PR review bot's triage) that the
    platform confirms here itself (``review.mechanical``: trust, but verify); a renamed file's old
    path too. What the check does not confirm stays in the diff; what is left out is kept on the run (audit)."""
    claimed = [dict(item) for item in dict(run.context or {}).get("review_summarized_paths") or []
               if isinstance(item, dict) and item.get("path")]
    left_out: list[tuple[str, str]] = []
    for item in claimed[:500]:
        path, old = str(item["path"]), str(item.get("old") or "")
        reason = await mechanical_reason(root, base, path, old=old)
        if not reason:
            continue
        left_out.append((path, f"mechanical change ({reason}): {path}"))
        if old:
            left_out.append((old, f"renamed to {path}: {old}"))
    if claimed:
        run.context = {**dict(run.context or {}), "review_left_out": [path for path, _line in left_out]}
    return left_out


__all__ = ["WHITESPACE_FREE", "mechanical_reason", "same_python_tree", "verified_mechanical"]
