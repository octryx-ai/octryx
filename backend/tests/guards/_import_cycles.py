from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping

from tests.guards._import_graph import ModuleIndex, _is_type_checking, resolve_relative

# The largest cycle of packages, counting the imports inside functions too: the structure debt after the loop
# deletion (WP-B2 measurement, 0.0.2 adffbcef). It may only shrink.
PACKAGE_CYCLE_BASELINE = 329
# A package is one level below these: app.services.workflow_runs, app.api.routes, app.web.routers; else app.<name>.
_SPLIT_PACKAGES = frozenset({"services", "api", "web", "agent"})


def _module_level(tree: ast.Module) -> Iterable[ast.AST]:
    for node in tree.body:
        if isinstance(node, ast.If) and _is_type_checking(node):
            continue
        yield node


def import_edges(index: ModuleIndex, module: str, *, module_level_only: bool) -> set[str]:
    tree = index.trees[module]
    nodes = _module_level(tree) if module_level_only else ast.walk(tree)
    found: set[str] = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative(index, module, node.level, node.module) if node.level else str(node.module)
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    # A package and its own submodules load each other by design; only imports between unrelated modules count.
    return {edge for edge in found if edge in index.trees and edge != module
            and not edge.startswith(module + ".") and not module.startswith(edge + ".")}


def cycles(graph: Mapping[str, set[str]]) -> list[list[str]]:
    number: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    found: list[list[str]] = []
    for root in sorted(graph):
        if root in number:
            continue
        # Iterative Tarjan: the module graph is deeper than Python's recursion limit.
        work = [(root, iter(sorted(graph.get(root, ()))))]
        number[root] = low[root] = len(number)
        stack.append(root)
        on_stack.add(root)
        while work:
            node, targets = work[-1]
            target = next(targets, None)
            if target is not None:
                if target not in number:
                    number[target] = low[target] = len(number)
                    stack.append(target)
                    on_stack.add(target)
                    work.append((target, iter(sorted(graph.get(target, ())))))
                elif target in on_stack:
                    low[node] = min(low[node], number[target])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == number[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1:
                    found.append(sorted(component))
    return sorted(found, key=len, reverse=True)


def import_time_cycles(index: ModuleIndex) -> list[list[str]]:
    return cycles({module: import_edges(index, module, module_level_only=True) for module in index.app_modules})


def package_of(module: str) -> str:
    parts = module.split(".")
    return ".".join(parts[:3]) if len(parts) > 2 and parts[1] in _SPLIT_PACKAGES else ".".join(parts[:2])


def largest_package_cycle(index: ModuleIndex) -> list[str]:
    graph: dict[str, set[str]] = {}
    for module in index.app_modules:
        for target in import_edges(index, module, module_level_only=False):
            if package_of(module) != package_of(target):
                graph.setdefault(package_of(module), set()).add(package_of(target))
    found = cycles(graph)
    return found[0] if found else []
