from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

IMPORT_ROOTS = ("clients/octryx-claude", "backend")
CONSOLE_SCRIPT_PROJECTS = ("backend/pyproject.toml", "clients/octryx-claude/pyproject.toml")
TOOL_REGISTRATION_DIR = "backend/app/tools/registry_impl/"
TOOL_LIST_PREFIX = "TOOL_CLASSES_"
ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "websocket", "api_route", "route"})
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEFINITIONS = (*_FUNCTIONS, ast.ClassDef)

Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def module_name(relative: str) -> str:
    for root in IMPORT_ROOTS:
        relative = relative.removeprefix(f"{root}/")
    parts = relative.removesuffix(".py").split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported_module(node: ast.ImportFrom, relative: str) -> str:
    if not node.level:
        return node.module or ""
    package = module_name(relative).split(".")
    if not relative.endswith("/__init__.py"):
        package = package[:-1]
    base = package[: len(package) - node.level + 1]
    return ".".join([*base, node.module] if node.module else base)


def _import_bindings(tree: ast.Module, relative: str) -> dict[str, tuple[str, str]]:
    bindings: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            source = _imported_module(node, relative)
            bindings.update({alias.asname or alias.name: (source, alias.name) for alias in node.names})
    return bindings


def _dunder_all(tree: ast.Module) -> set[str]:
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            value = node.value
            if isinstance(value, ast.List | ast.Tuple):
                return {item.value for item in value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
    return set()


def _is_main_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    operands = [node.test.left, *node.test.comparators]
    return any(isinstance(item, ast.Name) and item.id == "__name__" for item in operands) and any(
        isinstance(item, ast.Constant) and item.value == "__main__" for item in operands
    )


@dataclass
class PublicIndex:
    names: set[tuple[str, str]] = field(default_factory=set)
    star_modules: set[str] = field(default_factory=set)
    package_names: set[tuple[str, str]] = field(default_factory=set)

    def covers(self, module: str, name: str) -> bool:
        if (module, name) in self.names or (module in self.star_modules and not is_private(name)):
            return True
        parts = module.split(".")
        return any((".".join(parts[:end]), name) in self.package_names for end in range(1, len(parts)))

    def add_exports(self, relative: str, tree: ast.Module) -> None:
        package = module_name(relative)
        listed = _dunder_all(tree)
        bindings = _import_bindings(tree, relative)
        self.names.update(target for alias, target in bindings.items() if alias in listed or not is_private(alias))
        defined = {node.name for node in tree.body if isinstance(node, _DEFINITIONS)}
        self.names.update((package, name) for name in defined if name in listed or not is_private(name))
        self.star_modules.update(source for alias, (source, name) in bindings.items() if name == "*")
        self.package_names.update((package, name) for name in listed - bindings.keys() - defined)

    def add_registered_tools(self, relative: str, tree: ast.Module) -> None:
        bindings = _import_bindings(tree, relative)
        for node in tree.body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.List)):
                continue
            if any(isinstance(target, ast.Name) and target.id.startswith(TOOL_LIST_PREFIX) for target in node.targets):
                names = [item.id for item in node.value.elts if isinstance(item, ast.Name)]
                self.names.update(bindings.get(name, (module_name(relative), name)) for name in names)

    def add_entry_points(self, relative: str, tree: ast.Module) -> None:
        statements = tree.body if relative.endswith("/__main__.py") else [
            node for node in tree.body if _is_main_guard(node)
        ]
        bindings = _import_bindings(tree, relative) if statements else {}
        for statement in statements:
            for node in ast.walk(statement):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.names.add(bindings.get(node.func.id, (module_name(relative), node.func.id)))

    def add_console_scripts(self, root: Path) -> None:
        for project in CONSOLE_SCRIPT_PROJECTS:
            path = root / project
            if path.is_file():
                scripts = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
                for target in scripts.values():
                    module, _, function = target.partition(":")
                    self.names.add((module.strip(), function.strip().split(".")[0]))


def _declares_public_names(relative: str, source: str) -> bool:
    return relative.endswith(("/__init__.py", "/__main__.py")) or relative.startswith(TOOL_REGISTRATION_DIR) or (
        "__main__" in source
    )


def public_index(root: Path, sources: Mapping[str, str]) -> PublicIndex:
    index = PublicIndex()
    for relative, source in sources.items():
        if not _declares_public_names(relative, source):
            continue
        tree = ast.parse(source, filename=relative)
        if relative.endswith("/__init__.py"):
            index.add_exports(relative, tree)
        if relative.startswith(TOOL_REGISTRATION_DIR):
            index.add_registered_tools(relative, tree)
        index.add_entry_points(relative, tree)
    index.add_console_scripts(root)
    return index


def _is_interface_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)):
        return False
    owner = target.value.id
    return target.attr == "tool" or (target.attr in ROUTE_METHODS and (owner == "app" or owner.endswith("router")))


def classified_definitions(tree: ast.Module, relative: str, index: PublicIndex) -> Iterator[tuple[Definition, bool]]:
    in_tests = "tests" in Path(relative).parts
    module = module_name(relative)

    def walk(body: list[ast.stmt], *, top: bool, public_class: bool) -> Iterator[tuple[Definition, bool]]:
        for statement in body:
            if isinstance(statement, _DEFINITIONS):
                public = not in_tests and (
                    any(map(_is_interface_decorator, statement.decorator_list))
                    or (top and index.covers(module, statement.name))
                    or (public_class and isinstance(statement, _FUNCTIONS) and not is_private(statement.name))
                )
                yield statement, public
                yield from walk(statement.body, top=False, public_class=public and isinstance(statement, ast.ClassDef))
                continue
            for field_name in ("body", "orelse", "finalbody", "handlers", "cases"):
                for child in getattr(statement, field_name, ()):
                    nested = child.body if isinstance(child, ast.excepthandler | ast.match_case) else [child]
                    yield from walk(nested, top=top, public_class=public_class)

    return walk(tree.body, top=True, public_class=False)
