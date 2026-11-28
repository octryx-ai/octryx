"""Where every database session opened outside a request handler gets its data viewer."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
# Scripts and container entrypoints that open database sessions of their own, keyed like the app's modules.
SCRIPT_ROOTS = ((BACKEND / "scripts", BACKEND), (BACKEND.parent / "deployment" / "demo", BACKEND.parent))
VIEWER_BLOCKS = frozenset({"as_viewer", "platform_maintenance"})


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _opens_session(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and _name(node).endswith("session_factory") and not node.args


class _Sites(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path, self.scope, self.viewer_depth, self.sites = path, [], 0, []

    def _function(self, node) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node) -> None:  # noqa: N802 - ast.NodeVisitor's naming
        self._function(node)

    def visit_AsyncFunctionDef(self, node) -> None:  # noqa: N802
        self._function(node)

    def _with(self, node) -> None:
        declares = any(_name(item.context_expr) in VIEWER_BLOCKS for item in node.items)
        self.viewer_depth += declares
        self.generic_visit(node)
        self.viewer_depth -= declares

    def visit_With(self, node) -> None:  # noqa: N802
        self._with(node)

    def visit_AsyncWith(self, node) -> None:  # noqa: N802
        self._with(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _opens_session(node) and not self.viewer_depth:
            self.sites.append(f"{self.path}::{'.'.join(self.scope) or '<module>'}")
        self.generic_visit(node)


def undeclared_session_sites() -> set[str]:
    sites: set[str] = set()
    for key, path in _files():
        visitor = _Sites(key)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        sites.update(visitor.sites)
    return sites


def _calls(tree: ast.AST, names: frozenset[str]) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call) and _name(node) in names]


def _modules() -> list[tuple[str, ast.AST]]:
    return [(key, ast.parse(path.read_text(encoding="utf-8"))) for key, path in _files()]


def _files() -> list[tuple[str, Path]]:
    files = [(str(path.relative_to(BACKEND)), path) for path in sorted(APP.rglob("*.py"))]
    for root, base in SCRIPT_ROOTS:
        files += [(str(path.relative_to(base)), path) for path in sorted(root.glob("*.py"))]
    return files


def maintenance_sites() -> set[str]:
    sites = set()
    for path, tree in _modules():
        if path == "app/services/data_access/viewer.py":
            continue
        for call in _calls(tree, frozenset({"platform_maintenance"})):
            reason = call.args[0] if call.args else None
            text = reason.value if isinstance(reason, ast.Constant) else ast.unparse(reason) if reason else ""
            sites.add(f"{path}::{text}")
    return sites


def _sql_text_names(tree: ast.AST) -> frozenset[str]:
    return frozenset(alias.asname or alias.name for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy")
                     for alias in node.names if alias.name == "text")


def _receiver(call: ast.Call) -> str:
    func = call.func
    return _name(func.value) if isinstance(func, ast.Attribute) else ""


def connection_read_modules() -> set[str]:
    return {path for path, tree in _modules()
            if any(_name(call) == "connection" and not call.args
                   or _name(call) in ("connect", "begin") and "engine" in _receiver(call)
                   or _name(call) == "execute" and "conn" in _receiver(call)
                   for call in _calls(tree, frozenset({"connection", "connect", "begin", "execute"})))}


def table_clause_modules() -> set[str]:
    return {path for path, tree in _modules()
            if any(alias.name == "table" for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy")
                   for alias in node.names)}


def text_sql_modules() -> set[str]:
    found = set()
    for path, tree in _modules():
        index_where = {id(keyword.value) for node in ast.walk(tree) if isinstance(node, ast.Call)
                       for keyword in node.keywords if keyword.arg in ("postgresql_where", "sqlite_where")}
        calls = _calls(tree, _sql_text_names(tree) | {"exec_driver_sql"})
        if any(id(call) not in index_where for call in calls):
            found.add(path)
    return found
