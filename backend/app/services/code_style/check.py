"""The platform's own judgement of a change against the resolved code style, from the facts the launcher counts for the
changed files (``octryx_claude.run_contract.sizes``): never the engine's lint script, never the agent's word."""

from __future__ import annotations

import re
from fnmatch import fnmatch
from posixpath import basename
from typing import Any

from .defaults import language_of
from .finding import Finding
from .resolve import LEVELS


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) or fnmatch(path, pattern.replace("**/", "")) or
               fnmatch(path, pattern.rstrip("/") + "/*") for pattern in patterns)


def app_relative(path: str, roots: list[str]) -> str:
    parts = path.split("/")
    for index in range(len(parts)):
        rest = "/".join(parts[index:])
        if any(rest.startswith(str(root).rstrip("/") + "/") for root in roots if str(root).strip("/")):
            return rest
    return path


def style_for(path: str, style: dict[str, Any]) -> dict[str, Any]:
    language = language_of(path)
    return dict(dict(style.get("languages") or {}).get(language) or style.get("general") or {})


def _rank(source: Any) -> tuple[int, int]:
    text = str(source or "built_in")
    level = text.split(".")[0]
    return (LEVELS.index(level) if level in LEVELS else len(LEVELS), 0 if ".languages." in text else 1)


def _excluded(path: str, rules: dict[str, Any], rule: str) -> bool:
    best: tuple[tuple[int, int], bool] | None = None
    for kind in ("include", "exclude"):
        for row in rules.get(kind) or []:
            row = row if isinstance(row, dict) else {"glob": row}
            if not _matches(path, [str(row.get("glob"))]) or rule in (row.get("keep") or []):
                continue
            rank = _rank(row.get("source"))
            if best is None or rank < best[0]:
                best = (rank, kind == "exclude")
    return best is not None and best[1]


def _line_findings(path: str, lines: int, before: int | None, rules: dict[str, Any]) -> list[Finding]:
    test = _matches(path, [str(item) for item in rules.get("test_globs") or []])
    rule = "tests_max_lines" if test else "max_lines_per_file"
    limit = int(rules.get(rule) or 0)
    if not limit or lines <= limit:
        return []
    if before is None:
        return [Finding(rule, path, f"new file has {lines} lines (max {limit}): split it into smaller modules")]
    if before <= limit:
        return [Finding(rule, path, f"grew from {before} to {lines} lines (max {limit}): split it")]
    if lines > before:
        return [Finding(rule, path, f"was already over the limit ({before}) and grew to {lines} (max {limit}): do not "
                                    "add to this file; put the new code into a new module and import it")]
    return [Finding(rule, path, f"has {lines} lines (max {limit}); it was over the limit before this change",
                    severity="warning")]


def _function_finding(path: str, name: str, lines: int, limit: int, before: int | None) -> Finding:
    if before is not None and before > limit and lines <= before:
        return Finding("max_function_lines", path, f"function {name} has {lines} lines (max {limit}); it had {before} "
                       "before this change", severity="warning")
    return Finding("max_function_lines", path, f"function {name} has {lines} lines (max {limit}): extract helpers")


def _new_file_findings(path: str, rules: dict[str, Any]) -> list[Finding]:
    found: list[Finding] = []
    naming = dict(rules.get("naming") or {})
    if naming.get("file") and not re.search(str(naming["file"]), basename(path)):
        found.append(Finding("naming", path, f"file name does not match {naming['file']}"))
    layout = dict(rules.get("layout") or {})
    patterns = list(layout.get("patterns") or [])
    relative = app_relative(path, list(layout.get("roots") or []))
    if patterns and language_of(path) and not _matches(relative, patterns):
        found.append(Finding("layout", path, "file lies outside the layout ("
                             + ", ".join(patterns) + ")"))
    return found


def findings(style: dict[str, Any], sizes: Any) -> list[Finding]:
    if not isinstance(sizes, dict) or not style:
        return []
    files = sizes.get("files") if isinstance(sizes.get("files"), dict) else {}
    before = sizes.get("base_files") if isinstance(sizes.get("base_files"), dict) else {}
    found: list[Finding] = []
    for path, lines in sorted(files.items()):
        rules = style_for(str(path), style)
        if not isinstance(lines, int) or _excluded(str(path), rules, "max_lines_per_file"):
            continue
        prior = before.get(path)
        found += _line_findings(str(path), lines, prior if isinstance(prior, int) else None, rules)
        if prior is None:  # a new file: its name and place
            found += _new_file_findings(str(path), rules)
    earlier = {(str(entry[0]), str(entry[1])): entry[2] for entry in sizes.get("base_functions") or []
               if isinstance(entry, list) and len(entry) == 3 and isinstance(entry[2], int)}
    for entry in sizes.get("functions") or []:
        if isinstance(entry, list) and len(entry) == 3 and isinstance(entry[2], int):
            rules = style_for(str(entry[0]), style)
            limit = int(rules.get("max_function_lines") or 0)
            if limit and entry[2] > limit and not _excluded(str(entry[0]), rules, "max_function_lines"):
                found.append(_function_finding(str(entry[0]), str(entry[1]), entry[2], limit,
                                               earlier.get((str(entry[0]), str(entry[1])))))
    for entry in sizes.get("todos") or []:
        if isinstance(entry, list) and len(entry) == 3:
            rules = style_for(str(entry[0]), style)
            comments = dict(rules.get("comments") or {})
            pattern = str(comments.get("todo_pattern") or "")
            if comments.get("todo_requires_ticket") and pattern and not _excluded(str(entry[0]), rules,
                                                                                "todo_requires_ticket") \
                    and not re.search(pattern, str(entry[2])):
                found.append(Finding("todo_requires_ticket", str(entry[0]),
                                     f"TODO without a ticket (write it as {pattern})", line=int(entry[1])))
    for entry in sizes.get("long_lines") or []:
        if isinstance(entry, list) and len(entry) == 3 and isinstance(entry[2], int):
            rules = style_for(str(entry[0]), style)
            limit = int(rules.get("max_line_length") or 0)
            # Stylesheets ``keep`` this rule in the built-in style: a generated style.css can be one 4,974-character
            # line.
            if limit and entry[2] > limit and not _excluded(str(entry[0]), rules, "max_line_length"):
                found.append(Finding("max_line_length", str(entry[0]),
                                     f"line has {entry[2]} characters (max {limit}): wrap it; a URL or string that "
                                     "cannot be wrapped carries `octryx: allow-long-line`", line=int(entry[1])))
    for entry in sizes.get("commented_code") or []:
        if isinstance(entry, list) and len(entry) == 3:
            rules = style_for(str(entry[0]), style)
            if dict(rules.get("comments") or {}).get("no_commented_code") and not _excluded(str(entry[0]), rules,
                                                                                         "no_commented_code"):
                found.append(Finding("no_commented_code", str(entry[0]),
                                     f"{entry[2]} lines of commented-out code: delete them (git keeps history)",
                                     line=int(entry[1])))
    return found


__all__ = [
    "findings",
    "style_for",
]
