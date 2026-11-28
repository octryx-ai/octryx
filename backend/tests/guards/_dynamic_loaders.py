from __future__ import annotations

import ast
from collections.abc import Callable
from dataclasses import dataclass

from tests.guards._import_graph import ModuleIndex, call_name, literal_import_targets

GETATTR = "module __getattr__"
COMPUTED_IMPORT = "computed import_module"
FILE_LOADER = "spec_from_file_location"
COMPUTED_DUNDER_IMPORT = "computed __import__"
PACKAGE_SCAN = "package scan"


def detected_sites(index: ModuleIndex) -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for module in index.app_modules:
        tree = index.trees[module]
        if any(isinstance(node, ast.FunctionDef) and node.name == "__getattr__" for node in tree.body):
            sites.add((module, GETATTR))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            if name == "import_module" and literal_import_targets(index, module, node) is None:
                sites.add((module, COMPUTED_IMPORT))
            elif name == "spec_from_file_location":
                sites.add((module, FILE_LOADER))
            elif name == "__import__" and literal_import_targets(index, module, node) is None:
                sites.add((module, COMPUTED_DUNDER_IMPORT))
            elif name in {"walk_packages", "iter_modules"}:
                sites.add((module, PACKAGE_SCAN))
    return sites


def _assigned_value(index: ModuleIndex, module: str, target: str, *, anywhere: bool = False) -> ast.expr:
    nodes = ast.walk(index.trees[module]) if anywhere else iter(index.trees[module].body)
    for node in nodes:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == target for t in node.targets):
            return node.value
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == target and node.value:
            return node.value
    raise LookupError(f"{module}: no assignment to {target}")


def constant(index: ModuleIndex, module: str, target: str, *, anywhere: bool = False):
    value = _assigned_value(index, module, target, anywhere=anywhere)
    if isinstance(value, ast.Call) and call_name(value) in {"frozenset", "set", "tuple", "list"} and value.args:
        value = value.args[0]
    return ast.literal_eval(value)


def _absolute(package: str, relative: str) -> str:
    level = len(relative) - len(relative.lstrip("."))
    base = package
    for _ in range(level - 1):
        base = base.rpartition(".")[0]
    return f"{base}.{relative.lstrip('.')}" if level else relative


def _submodules(module: str, table: str) -> Callable[[ModuleIndex], set[str]]:
    return lambda index: {f"{module}.{name}" for name in constant(index, module, table)}


def _table_values(module: str, *tables: str, relative_to: str | None = None,
                  prefix: str = "") -> Callable[[ModuleIndex], set[str]]:
    def targets(index: ModuleIndex) -> set[str]:
        values = {prefix + value for table in tables for value in constant(index, module, table).values()}
        return {_absolute(relative_to, value) if relative_to else value for value in values}

    return targets


def _nothing(index: ModuleIndex) -> set[str]:
    return set()


def _plugin_classes(index: ModuleIndex) -> set[str]:
    return {_absolute("app.plugins", row[1]) for row in constant(index, "app.plugins", "_to_register", anywhere=True)}


def _plugin_directory(index: ModuleIndex) -> set[str]:
    return {
        name for name in index.app_modules
        if name.rpartition(".")[0] == "app.plugins" and not name.rpartition(".")[2].startswith("_")
    }


def _intake_sources(index: ModuleIndex) -> set[str]:
    targets = set()
    for node in index.trees["app.services.secure_work.intake.registry"].body:
        call = node.value if isinstance(node, ast.Expr) else None
        if isinstance(call, ast.Call) and call_name(call) == "register":
            entry = call.args[0]
            targets.add(ast.literal_eval(entry.args[3]).partition(":")[0])
    return targets


def _on_done_callbacks(index: ModuleIndex) -> set[str]:
    targets = set()
    for module in index.app_modules:
        for node in ast.walk(index.trees[module]):
            if not isinstance(node, ast.keyword) or node.arg != "on_done":
                continue
            value = node.value
            if isinstance(value, ast.Name):
                try:
                    value = ast.Constant(constant(index, module, value.id))
                except LookupError:
                    continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                targets.add("app.services." + value.value.partition(":")[0])
    return targets


@dataclass(frozen=True)
class Loader:
    module: str
    kinds: frozenset[str]
    targets: Callable[[ModuleIndex], set[str]]
    note: str


def _loader(module: str, kinds: set[str], targets: Callable[[ModuleIndex], set[str]], note: str) -> Loader:
    return Loader(module, frozenset(kinds), targets, note)


# A lazy package counts as loading its whole table: once it is reached, any of its names can be asked for.
LOADERS: tuple[Loader, ...] = (
    _loader("app.web", {GETATTR}, _nothing, "router built on first access; its routers load by literal name"),
    _loader("app.tools", {GETATTR}, _nothing, "registry exports load '.registry' by literal name"),
    _loader("app.services.worker", {GETATTR}, _nothing, "exports load '.service' by literal name"),
    _loader("app.services.system_config", {GETATTR}, _nothing, "one name, imported statically inside"),
    _loader("app.services.stt", {GETATTR}, _nothing, "cloud services, imported statically inside"),
    _loader("app.services.observability", {GETATTR, COMPUTED_IMPORT},
            _table_values("app.services.observability", "_EXPORTS", relative_to="app.services.observability"),
            "_EXPORTS: name -> module relative to the package"),
    _loader("app.services.session", {GETATTR, COMPUTED_IMPORT},
            _submodules("app.services.session", "_PUBLIC_MODULES"), "_PUBLIC_MODULES: submodules"),
    _loader("app.services.office", {GETATTR, COMPUTED_IMPORT},
            _submodules("app.services.office", "_PUBLIC_MODULES"), "_PUBLIC_MODULES: submodules"),
    _loader("app.services.code_intelligence", {GETATTR, COMPUTED_IMPORT},
            lambda index: _submodules("app.services.code_intelligence", "_PUBLIC_MODULES")(index)
            | _table_values("app.services.code_intelligence", "_PUBLIC_FUNCTION_MODULES")(index),
            "_PUBLIC_MODULES: submodules; _PUBLIC_FUNCTION_MODULES: name -> module"),
    _loader("app.plugins", {COMPUTED_IMPORT}, _plugin_classes, "_to_register: the known channel plugin classes"),
    _loader("app.plugins.core.manager", {COMPUTED_IMPORT, FILE_LOADER}, _plugin_directory,
            "discover_plugins: scans the app/plugins directory"),
    _loader("app.tools.runtime_impl._runtime_code_service_resolvers", {COMPUTED_IMPORT},
            _table_values("app.tools.runtime_impl._runtime_code_service_resolvers",
                          "_CODE_INTELLIGENCE_OWNERS", "_RUNTIME_SERVICE_OWNERS"),
            "service name -> owning module tables"),
    _loader("app.services.workflow_runs.documentation.s1_graph", {COMPUTED_IMPORT},
            _table_values("app.services.workflow_runs.documentation.s1_graph", "INTERFACES",
                          prefix="app.services.workflow_runs.documentation."),
            "INTERFACES: name -> module of the documentation package"),
    _loader("app.services.workflow_runs.review.spec_evidence", {COMPUTED_IMPORT},
            lambda index: {constant(index, "app.services.workflow_runs.review.spec_evidence", "RESOLVER_MODULE")},
            "RESOLVER_MODULE constant"),
    _loader("app.services.secure_work.intake.registry", {COMPUTED_IMPORT}, _intake_sources,
            "register(SourceEntry(...)) rows: '<module>:<attribute>'"),
    _loader("app.services.devices.tool_jobs", {COMPUTED_IMPORT}, _on_done_callbacks,
            "on_done='<module>:<name>' of the job producers, under app.services"),
    _loader("app.services.redaction_policy", {FILE_LOADER}, _nothing, "loads backend/scripts/secret_patterns.py"),
    _loader("app.services.session_transcripts.redaction", {FILE_LOADER}, _nothing,
            "loads backend/scripts/transcript_secrets.py"),
)


def modelled_sites() -> set[tuple[str, str]]:
    return {(loader.module, kind) for loader in LOADERS for kind in loader.kinds}


def dynamic_edges(index: ModuleIndex) -> dict[str, set[str]]:
    edges: dict[str, set[str]] = {}
    for loader in LOADERS:
        if loader.module not in index.trees:
            continue
        targets = loader.targets(index)
        missing = sorted(target for target in targets if target not in index.trees)
        if missing:
            raise LookupError(f"{loader.module}: modelled targets are not modules: {missing}")
        edges[loader.module] = targets
    return edges
