"""The code size facts of a change (``run_contract.facts``): lines per changed file, long Python functions, long
added lines, TODOs and commented-out code, also at the base. The launcher only counts; the server compares."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from . import os_junk
from .contract_change import _SHA, CHANGE_GIT_TIMEOUT, _git

MAX_SIZED_FILES = 300
MAX_SIZED_BYTES = 1_000_000
REPORTED_FUNCTION_LINES = 20  # only functions at least this long are reported (the server compares its limit)
# The line length. Only lines the change adds are reported, longer than the smallest limit of the
# style; a line carrying LONG_LINE_MARKER (a URL or a string that cannot be wrapped) is never reported.
LONG_LINE_MARKER = "octryx: allow-long-line"
MAX_LONG_LINES_PER_FILE = 30
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def line_floor(style: Any) -> int:
    if not isinstance(style, dict):
        return 0
    limits = [dict(style.get("general") or {}).get("max_line_length")]
    limits += [dict(rules or {}).get("max_line_length") for rules in dict(style.get("languages") or {}).values()]
    found = [limit for limit in limits if isinstance(limit, int) and limit > 0]
    return min(found) if found else 0


def _added_lines(diff: str) -> dict[str, set[int]]:
    added: dict[str, set[int]] = {}
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else ""
        elif current and (hunk := _HUNK.match(line)):
            start, count = int(hunk.group(1)), int(hunk.group(2) if hunk.group(2) is not None else 1)
            added.setdefault(current, set()).update(range(start, start + count))
    return added


def _long_lines(name: str, text: str, floor: int, added: set[int] | None) -> list[list[Any]]:
    found = [[name, number, len(line)] for number, line in enumerate(text.splitlines(), 1)
             if len(line) > floor and (added is None or number in added) and LONG_LINE_MARKER not in line]
    return sorted(found, key=lambda item: -item[2])[:MAX_LONG_LINES_PER_FILE]


def _python_functions(text: str) -> list[tuple[str, int]]:
    import ast

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: list[tuple[str, int]] = []

    def walk(node: Any, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    found.append((name, int(child.end_lineno or child.lineno) - int(child.lineno) + 1))
                walk(child, f"{name}.")
    walk(tree, "")
    return found


def sizes(root: Path, base: str, long_line_floor: int = 0) -> dict[str, Any]:
    if not _SHA.match(base or ""):
        return {}
    with tempfile.TemporaryDirectory(prefix="octryx-sizes-") as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        steps = [_git(root, "read-tree", "HEAD", env=env, timeout=CHANGE_GIT_TIMEOUT),
                 _git(root, *os_junk.add_all(), env=env, timeout=CHANGE_GIT_TIMEOUT)]
        if any(step is None or step.returncode != 0 for step in steps):
            return {}
        names = _git(root, "diff", "--cached", "--name-only", "--diff-filter=AM", "--no-renames", base, env=env)
        modified = _git(root, "diff", "--cached", "--name-only", "--diff-filter=M", "--no-renames", base, env=env)
        hunks = _git(root, "diff", "--cached", "-U0", "--no-color", "--no-ext-diff", "--no-renames",
                     "--diff-filter=M", base, env=env, timeout=CHANGE_GIT_TIMEOUT) if long_line_floor else None
    if names is None or names.returncode != 0:
        return {}
    from .style_facts import base_texts, commented_code, todos

    files: dict[str, int] = {}
    functions: list[list[Any]] = []
    found_todos: list[list[Any]] = []
    blocks: list[list[Any]] = []
    long_lines: list[list[Any]] = []
    changed_names = set(modified.stdout.splitlines()) if modified is not None and modified.returncode == 0 else set()
    added = _added_lines(hunks.stdout) if hunks is not None and hunks.returncode == 0 else {}
    for name in [line for line in names.stdout.splitlines() if line.strip()][:MAX_SIZED_FILES]:
        path = (root / name)
        try:
            if not path.is_file() or path.stat().st_size > MAX_SIZED_BYTES:
                continue
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary or unreadable: no line count
        files[name] = len(text.splitlines())
        if name.endswith(".py"):
            functions += [[name, qualified, lines] for qualified, lines in _python_functions(text)
                          if lines >= REPORTED_FUNCTION_LINES]
        found_todos += todos(name, text)
        if long_line_floor:
            long_lines += _long_lines(name, text, long_line_floor, added.get(name, set()) if name in changed_names
                                      else None)
        blocks += commented_code(name, text)
    changed = [line for line in (modified.stdout.splitlines() if modified is not None and modified.returncode == 0
                                 else []) if line in files]
    # A file already over the limit before the change only warns unless it grows. The same for a
    # function (four functions already 69-82 lines long at the base, shrunk by the agent, held
    # the story red): the base's long functions of the modified Python files go up too.
    before = base_texts(root, base, changed, timeout=CHANGE_GIT_TIMEOUT)
    base_functions = [[name, qualified, lines] for name, text in before.items() if name.endswith(".py")
                      for qualified, lines in _python_functions(text) if lines >= REPORTED_FUNCTION_LINES]
    return {"files": files, "functions": functions[:MAX_SIZED_FILES], "todos": found_todos[:200],
            "commented_code": blocks[:100], **({"long_lines": long_lines[:500]} if long_line_floor else {}),
            "base_files": {name: len(text.splitlines()) for name, text in before.items()},
            "base_functions": base_functions[:MAX_SIZED_FILES]}
