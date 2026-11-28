from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from tests.guards._support import BACKEND

PACKAGE = "app"
# These modules hold Python script templates that the Office tools write out and run; the imports inside the
# template text are real dependencies.
GENERATED_SCRIPT_SOURCES = frozenset({
    "app.tools.office_impl._office_excel_script_template",
    "app.tools.office_impl._office_presentation_script_template",
    "app.tools.office_impl._office_word_script_template_core",
})
# Files outside app/ (migrations, scripts) are entry points rather than importable modules; the prefix keeps their
# names from ever matching an import target.
ENTRY_FILE_PREFIX = "<file>"
LITERAL_IMPORT_CALLS = frozenset({"import_module", "__import__"})
_EMBEDDED_IMPORT = re.compile(
    r"^[ \t]*(?:from[ \t]+(app(?:\.\w+)*)[ \t]+import[ \t]+([\w, \t]+)|import[ \t]+(app(?:\.\w+)*))", re.MULTILINE
)


@dataclass
class ModuleIndex:
    trees: dict[str, ast.Module] = field(default_factory=dict)
    packages: set[str] = field(default_factory=set)
    paths: dict[str, str] = field(default_factory=dict)

    @property
    def app_modules(self) -> set[str]:
        return {name for name in self.trees if name == PACKAGE or name.startswith(PACKAGE + ".")}

    def package_of(self, module: str) -> str:
        return module if module in self.packages else module.rpartition(".")[0]


def module_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def index_sources(sources: Mapping[str, str]) -> ModuleIndex:
    index = ModuleIndex()
    for relative, text in sources.items():
        path = Path(relative)
        in_package = path.parts[0] == PACKAGE
        name = module_name(path) if in_package else f"{ENTRY_FILE_PREFIX}{relative}"
        index.trees[name] = ast.parse(text, filename=relative)
        index.paths[name] = relative
        if in_package and path.name == "__init__.py":
            index.packages.add(name)
    return index


@cache
def app_sources() -> dict[str, str]:
    return {
        path.relative_to(BACKEND).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((BACKEND / PACKAGE).rglob("*.py"))
        if "__pycache__" not in path.parts
    }


def resolve_relative(index: ModuleIndex, module: str, level: int, name: str | None) -> str:
    base = index.package_of(module)
    for _ in range(level - 1):
        base = base.rpartition(".")[0]
    return f"{base}.{name}" if name else base


def _is_type_checking(node: ast.AST) -> bool:
    test = node.test if isinstance(node, ast.If) else None
    return isinstance(test, ast.Name | ast.Attribute) and ast.unparse(test).endswith("TYPE_CHECKING")


def _walk_runtime(tree: ast.AST) -> Iterable[ast.AST]:
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        if _is_type_checking(node):
            stack.extend(node.orelse)
            continue
        stack.extend(ast.iter_child_nodes(node))


def call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""


def _literal(call: ast.Call, position: int, keyword: str) -> ast.expr | None:
    if len(call.args) > position:
        return call.args[position]
    return next((item.value for item in call.keywords if item.arg == keyword), None)


def literal_import_targets(index: ModuleIndex, module: str, call: ast.Call) -> set[str] | None:
    name = _literal(call, 0, "name")
    if not isinstance(name, ast.Constant) or not isinstance(name.value, str):
        return None
    target: str = name.value
    if call_name(call) == "import_module":
        dots = len(target) - len(target.lstrip("."))
        return {resolve_relative(index, module, dots, target.lstrip(".") or None) if dots else target}
    # __import__(name, globals, locals, fromlist, level): the from-list names submodules of the named one.
    level, fromlist = _literal(call, 4, "level"), _literal(call, 3, "fromlist")
    if level is not None and not (isinstance(level, ast.Constant) and type(level.value) is int):
        return None
    names: list[str] = []
    if fromlist is not None and not (isinstance(fromlist, ast.Constant) and fromlist.value is None):
        if not isinstance(fromlist, ast.List | ast.Tuple) or not all(
                isinstance(item, ast.Constant) and isinstance(item.value, str) for item in fromlist.elts):
            return None
        names = [item.value for item in fromlist.elts]
    depth = level.value if level is not None else 0
    base = resolve_relative(index, module, depth, target or None) if depth else target
    return {base, *(f"{base}.{item}" for item in names if item != "*")}


def _embedded_imports(text: str) -> set[str]:
    edges = set()
    for match in _EMBEDDED_IMPORT.finditer(text):
        base = match.group(1) or match.group(3)
        edges.add(base)
        edges.update(f"{base}.{name.strip()}" for name in (match.group(2) or "").split(",") if name.strip())
    return edges


def _emitted_script_text(tree: ast.AST) -> Iterable[str]:
    # Only what a renderer returns is written out as a script; docstrings and other prose are not.
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            for part in ast.walk(node.value):
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield part.value


def static_edges(index: ModuleIndex, module: str) -> set[str]:
    edges: set[str] = set()
    if "." in module and not module.startswith(ENTRY_FILE_PREFIX):
        edges.add(module.rpartition(".")[0])
    if module in GENERATED_SCRIPT_SOURCES:
        for text in _emitted_script_text(index.trees[module]):
            edges.update(_embedded_imports(text))
    for node in _walk_runtime(index.trees[module]):
        if isinstance(node, ast.Import):
            edges.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(index, module, node.level, node.module) if node.level else node.module or ""
            edges.add(base)
            edges.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call) and call_name(node) in LITERAL_IMPORT_CALLS:
            edges.update(literal_import_targets(index, module, node) or ())
    return {edge for edge in edges if edge in index.trees}


def reachable(index: ModuleIndex, roots: Iterable[str], extra_edges: Mapping[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [root for root in roots if root in index.trees]
    while stack:
        module = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        for target in static_edges(index, module) | extra_edges.get(module, set()):
            parts = target.split(".")
            stack.extend(".".join(parts[:i]) for i in range(1, len(parts) + 1) if ".".join(parts[:i]) in index.trees)
    return seen
