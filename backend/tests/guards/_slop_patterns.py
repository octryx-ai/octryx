from __future__ import annotations

import ast
import io
import tokenize
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from tests.guards._support import REPO_ROOT

SCANNED = ("backend/app", "clients/octryx-claude/octryx_claude")
SKIPPED_DIRS = frozenset({"__pycache__", ".venv", "venv", "node_modules", "build", "dist"})
RULES = (
    "pass-through wrappers",
    "catch-all excepts without a reason",
    "compat aliases",
    "lines over 300 per file",
    "lines over 60 per function",
)
MAX_FILE_LINES = 300
MAX_FUNCTION_LINES = 60
_CATCH_ALL = frozenset({"Exception", "BaseException"})
_TYPING_NAMES = frozenset({"Any", "Callable", "TypeAlias", "Protocol", "TypeVar"})
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
REGENERATE = ".venv/bin/python -m tests.guards._slop_patterns (from backend/)"
BASELINE_FILE = Path(__file__).with_name("_slop_patterns_baseline.py")

Counts = tuple[int, int, int, int, int]
NO_COUNTS: Counts = (0, 0, 0, 0, 0)


def scanned_files(root: Path) -> Iterator[Path]:
    for top in SCANNED:
        for path in sorted((root / top).rglob("*.py")):
            if not SKIPPED_DIRS.intersection(path.relative_to(root).parts[:-1]):
                yield path


def _body_without_docstring(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    body = node.body
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _forwards_its_parameters(call: ast.Call, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    arguments = node.args
    if arguments.vararg or arguments.kwarg:
        return False
    names = [a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)]
    if names and names[0] in {"self", "cls"}:
        return False
    passed = [a.id for a in call.args if isinstance(a, ast.Name)]
    if len(passed) != len(call.args):
        return False
    for keyword in call.keywords:
        if keyword.arg is None or not isinstance(keyword.value, ast.Name) or keyword.value.id != keyword.arg:
            return False
        passed.append(keyword.arg)
    return bool(names) and passed == names


# A plain function whose whole body hands its own parameters, unchanged and in order, to one other call.
def is_pass_through(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if node.name.startswith("__") or node.decorator_list:
        return False
    body = _body_without_docstring(node)
    if len(body) != 1 or not isinstance(body[0], ast.Return | ast.Expr):
        return False
    value = body[0].value
    if isinstance(value, ast.Await):
        value = value.value
    return isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and _forwards_its_parameters(value, node)


def _is_catch_all(handler: ast.ExceptHandler) -> bool:
    caught = handler.type
    if caught is None:
        return True
    names = caught.elts if isinstance(caught, ast.Tuple) else [caught]
    return any(isinstance(name, ast.Name) and name.id in _CATCH_ALL for name in names)


def _reraises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(ast.Module(body=handler.body, type_ignores=[])))


def _unreasoned_catch_alls(tree: ast.Module, comment_lines: set[int]) -> int:
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not _is_catch_all(node) or _reraises(node):
            continue
        reason_lines = range(node.lineno, node.body[0].lineno + 1)
        if not comment_lines.intersection(reason_lines):
            count += 1
    return count


def _compat_aliases(tree: ast.Module) -> int:
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (*_FUNCTIONS, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            defined.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
    count = 0
    for node in tree.body:
        # A second name for a function or class; constants named after their use are not aliases.
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Name) and node.value.id in defined
                and node.value.id not in _TYPING_NAMES and not node.value.id.isupper()
                and not node.targets[0].id.isupper() and not node.targets[0].id.startswith("__")):
            count += 1
    return count


def _function_excess(tree: ast.Module) -> int:
    return sum(
        max(0, node.end_lineno - node.lineno + 1 - MAX_FUNCTION_LINES)
        for node in ast.walk(tree) if isinstance(node, _FUNCTIONS)
    )


def file_counts(source: str, tree: ast.Module) -> Counts:
    comment_lines = {
        token.start[0] for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    }
    wrappers = sum(1 for node in ast.walk(tree) if isinstance(node, _FUNCTIONS) and is_pass_through(node))
    file_excess = max(0, len(source.splitlines()) - MAX_FILE_LINES)
    return (wrappers, _unreasoned_catch_alls(tree, comment_lines), _compat_aliases(tree), file_excess,
            _function_excess(tree))


def slop_counts(root: Path, files: Iterable[Path]) -> dict[str, Counts]:
    found: dict[str, Counts] = {}
    for path in files:
        relative = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        counts = file_counts(source, ast.parse(source, filename=relative))
        if any(counts):
            found[relative] = counts
    return found


def ratchet_problems(found: Mapping[str, Counts], baseline: Mapping[str, Counts]) -> list[str]:
    problems: list[str] = []
    for key in sorted(found.keys() | baseline.keys()):
        now, allowed = found.get(key, NO_COUNTS), baseline.get(key, NO_COUNTS)
        for rule, count, limit in zip(RULES, now, allowed, strict=True):
            if count > limit:
                problems.append(f"{key}: {rule} {count}, baseline {limit}: fix the new ones")
            elif count < limit:
                problems.append(f"{key}: {rule} {count}, baseline {limit}: lower the baseline ({REGENERATE})")
    return problems


def baseline_source(found: Mapping[str, Counts]) -> str:
    rows = "".join(f'    "{path}": {counts},\n' for path, counts in sorted(found.items()))
    return (
        "from __future__ import annotations\n\n"
        f"# Generated by `{REGENERATE}`.\n"
        "# Columns: _slop_patterns.RULES in order.\n"
        f"SLOP_BASELINE: dict[str, tuple[int, int, int, int, int]] = {{\n{rows}}}\n"
    )


if __name__ == "__main__":
    BASELINE_FILE.write_text(baseline_source(slop_counts(REPO_ROOT, scanned_files(REPO_ROOT))), encoding="utf-8")
