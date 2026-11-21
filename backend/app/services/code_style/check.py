"""The platform's own judgement of a change against the resolved code style, from the facts the
launcher counts for the changed files (``octryx_claude.run_contract.sizes``): never the engine's lint script, never
the agent's word.

Rules (``rule`` ids in each finding):

- ``max_lines_per_file`` / ``tests_max_lines``: a **new** file over its limit, a file the change **grows past** the
  limit, or one **already over it that grows** is an error; a file that was already over the limit and does not grow
  is a warning (touched legacy files only warn);
- ``max_function_lines``: a function over the limit (Python; Dart and TypeScript once a parser counts them);
- ``naming``: a new file whose name does not match the language's file pattern;
- ``layout``: a new file of a language with layout patterns outside them;
- ``todo_requires_ticket``: a TODO / FIXME line without the ticket pattern;
- ``no_commented_code``: a block of commented-out code.

Which files a rule judges is data (``built_in.json`` and the levels above it), never a list in this module:

=================================  ====================================================================
``exclude`` row (``glob``)         the file is not judged (generated, l10n, documentation, scaffold, ...)
``exclude`` row with ``keep``      not judged, except by the rules named in ``keep`` (a stylesheet keeps
                                   ``max_line_length``)
``include`` glob                   judged after all, against an exclude of a less specific level
two levels match                   the most specific level decides: repository > Workspace >
                                   installation > built in; a language's own rows before its level's
                                   general ones
the same level has both            ``include`` wins
=================================  ====================================================================
"""

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
    """``path`` from the app's own folder: an app in a subfolder (``coffee/flutter/claude/test/x_test.dart``) is
    matched from its first layout root (``test/x_test.dart``). Unchanged when
    no root occurs in it."""
    parts = path.split("/")
    for index in range(len(parts)):
        rest = "/".join(parts[index:])
        if any(rest.startswith(str(root).rstrip("/") + "/") for root in roots if str(root).strip("/")):
            return rest
    return path


def style_for(path: str, style: dict[str, Any]) -> dict[str, Any]:
    """The resolved style of ``path``'s language (``style``: ``{general, languages}`` from the contract)."""
    language = language_of(path)
    return dict(dict(style.get("languages") or {}).get(language) or style.get("general") or {})


def _rank(source: Any) -> tuple[int, int]:
    """How specific a row's level is (lower wins): repository before Workspace before installation before built in,
    and within a level its language's own rows before the general ones."""
    text = str(source or "built_in")
    level = text.split(".")[0]
    return (LEVELS.index(level) if level in LEVELS else len(LEVELS), 0 if ".languages." in text else 1)


def _excluded(path: str, rules: dict[str, Any], rule: str) -> bool:
    """Whether ``rule`` skips ``path``: the most specific level with a matching ``include`` or ``exclude`` row
    decides, an ``include`` winning a tie; an exclude row that names ``rule`` in its ``keep`` does not count for it."""
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
    """A function over its limit: an error when it is new, was within the limit or grew; a warning when it was
    already over the limit before the change and did not grow (old debt the agent even
    shrank must not hold the story red)."""
    if before is not None and before > limit and lines <= before:
        return Finding("max_function_lines", path, f"function {name} has {lines} lines (max {limit}); it had {before} "
                       "before this change", severity="warning")
    return Finding("max_function_lines", path, f"function {name} has {lines} lines (max {limit}): extract helpers")


def _new_file_findings(path: str, rules: dict[str, Any]) -> list[Finding]:
    """A new file's name against the language's file pattern and its place against the layout."""
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
    """Every finding of the change, errors and warnings."""
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
