"""FastAPI routes for the context pack: method, full path, handler and the dependencies that guard it."""

from __future__ import annotations

import ast
from pathlib import Path

METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
GUARDS = frozenset({"Depends", "Security"})
MAX_ROUTE_FILE_BYTES = 200_000

Route = tuple[str, int, str, str, str, list[str]]  # file, line, METHOD, path, handler, dependencies


def _name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _guard(node: ast.AST) -> str:
    if isinstance(node, ast.Call) and _name(node.func) in GUARDS and node.args:
        return _name(node.args[0])
    return ""


def _listed(node: ast.AST | None) -> list[str]:
    items = node.elts if isinstance(node, ast.List | ast.Tuple) else []
    return [name for name in (_guard(item) for item in items) if name]


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    return next((item.value for item in call.keywords if item.arg == name), None)


def _routers(tree: ast.Module) -> dict[str, tuple[str, list[str]]]:
    found: dict[str, tuple[str, list[str]]] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and _name(node.value.func) in ("APIRouter", "FastAPI")):
            continue
        prefix = _keyword(node.value, "prefix")
        text = prefix.value if isinstance(prefix, ast.Constant) and isinstance(prefix.value, str) else ""
        for target in node.targets:
            if isinstance(target, ast.Name):
                found[target.id] = (text, _listed(_keyword(node.value, "dependencies")))
    return found


def _parameter_guards(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    found = []
    arguments = function.args
    for default in [*arguments.defaults, *arguments.kw_defaults]:
        if default is not None and _guard(default):
            found.append(_guard(default))
    for argument in [*arguments.args, *arguments.kwonlyargs]:
        annotation = argument.annotation
        if isinstance(annotation, ast.Subscript) and _name(annotation.value) == "Annotated":
            parts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else []
            found += [name for name in (_guard(item) for item in parts) if name]
    return found


def _decorated(name: str, function: ast.FunctionDef | ast.AsyncFunctionDef,
               routers: dict[str, tuple[str, list[str]]]) -> list[Route]:
    found: list[Route] = []
    for decorator in function.decorator_list:
        if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in METHODS and decorator.args):
            continue
        path = decorator.args[0]
        if not (isinstance(path, ast.Constant) and isinstance(path.value, str)):
            continue
        prefix, shared = routers.get(_name(decorator.func.value), ("", []))
        guards = [*shared, *_listed(_keyword(decorator, "dependencies")), *_parameter_guards(function)]
        found.append((name, function.lineno, decorator.func.attr.upper(), prefix + path.value, function.name,
                      list(dict.fromkeys(guards))))
    return found


def fastapi_routes(root: str, files: list[str]) -> list[Route]:
    found: list[Route] = []
    for name in files:
        if not name.endswith(".py"):
            continue
        path = Path(root) / name
        try:
            if path.stat().st_size > MAX_ROUTE_FILE_BYTES:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            if "fastapi" not in source:
                continue
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            continue
        routers = _routers(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                found += _decorated(name, node, routers)
    return found


__all__ = ["Route", "fastapi_routes"]
