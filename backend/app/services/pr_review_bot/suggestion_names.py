"""Whether a one-click suggestion still runs once applied."""

from __future__ import annotations

import ast
import builtins
from typing import Any

PYTHON_SUFFIXES = (".py",)
_BUILTINS = frozenset(dir(builtins)) | {"__name__", "__file__", "__doc__", "__spec__", "__package__"}


def applied(source: str, start: int, end: int, suggestion: str) -> str:
    lines = source.split("\n")
    return "\n".join([*lines[: start - 1], *suggestion.rstrip("\n").split("\n"), *lines[end:]])


def _bound(tree: ast.AST) -> set[str] | None:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if alias.name == "*":
                    return None
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif isinstance(node, (ast.MatchAs, ast.MatchStar)) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
    return names


def python_problem(source: str, start: int, end: int, suggestion: str) -> str:
    first, last = start, start + len(suggestion.rstrip("\n").split("\n")) - 1
    try:
        tree = ast.parse(applied(source, start, end, suggestion))
    except SyntaxError as error:
        return f"the file would not parse ({error.msg}, line {error.lineno})"
    bound = _bound(tree)
    if bound is None:
        return ""
    unknown = sorted({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
                      and isinstance(node.ctx, ast.Load) and first <= node.lineno <= last
                      and node.id not in bound and node.id not in _BUILTINS})
    return f"it uses {', '.join(f'`{name}`' for name in unknown)}, which the file does not define" if unknown else ""


def problem(path: str, source: str | None, start: int, end: int, suggestion: str) -> str:
    if source is None or not path.endswith(PYTHON_SUFFIXES):
        return ""
    return python_problem(source, start, end, suggestion)


async def sources(root: str, head: str, findings: list[Any]) -> dict[str, str]:
    from ..workflow_runs import safe_git

    paths = sorted({str(item.get("file") or "").strip().lstrip("./") for item in findings if isinstance(item, dict)
                    and str(item.get("suggestion") or "").strip()
                    and str(item.get("file") or "").endswith(PYTHON_SUFFIXES)})
    found: dict[str, str] = {}
    for path in paths if root and head else []:
        code, text, _err = await safe_git.git(root, "show", f"{head}:{path}")
        if code == 0:
            found[path] = text
    return found


__all__ = ["applied", "problem", "python_problem", "sources"]
