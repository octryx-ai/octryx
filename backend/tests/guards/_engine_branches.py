from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterable

from tests.guards._import_graph import ModuleIndex, call_name

ENGINE_AND_VENDOR_NAMES = frozenset({
    "anthropic", "claude", "claude_code", "codex", "gemini", "openai", "opencode",
})
PROVIDER_REGISTRY = "app.agent.providers.provider_registry"
_PREFIX = re.compile(r"^[a-z_]+")


# "google" is also the Google sign-in provider and a cloud in the diagram icons.
AMBIGUOUS_NAMES = frozenset({"google"})


def vocabulary(index: ModuleIndex) -> frozenset[str]:
    names = set(ENGINE_AND_VENDOR_NAMES)
    tree = index.trees.get(PROVIDER_REGISTRY)
    for node in tree.body if tree else ():
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if getattr(target, "id", None) != "DRIVER_SPECS" or not isinstance(node.value, ast.Dict):
            continue
        names.update(key.value for key in node.value.keys if isinstance(key, ast.Constant))
        for spec in node.value.values:
            names.update(kw.value.value for kw in getattr(spec, "keywords", ())
                         if kw.arg == "default_name" and isinstance(kw.value, ast.Constant))
    return frozenset(names - AMBIGUOUS_NAMES)


def named_constants(index: ModuleIndex, names: frozenset[str]) -> frozenset[str]:
    found = set()
    for module in index.app_modules:
        for node in index.trees[module].body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and node.value.value in names:
                found.update(t.id for t in node.targets if isinstance(t, ast.Name) and t.id.isupper())
    return frozenset(found)


def _names_in(node: ast.expr, names: frozenset[str], constants: frozenset[str]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.lower() in names:
        return {node.value.lower()}
    if isinstance(node, ast.Name | ast.Attribute):
        identifier = node.id if isinstance(node, ast.Name) else node.attr
        return {identifier} if identifier in constants else set()
    if isinstance(node, ast.Set | ast.Tuple | ast.List):
        return {name for element in node.elts for name in _names_in(element, names, constants)}
    if isinstance(node, ast.Call) and call_name(node) in {"frozenset", "set", "tuple"} and node.args:
        return _names_in(node.args[0], names, constants)
    return set()


def _special_cases(test: ast.AST, names: frozenset[str], constants: frozenset[str]) -> set[str]:
    hits: set[str] = set()
    for node in ast.walk(test):
        if isinstance(node, ast.Compare) and all(
            isinstance(op, ast.Eq | ast.NotEq | ast.In | ast.NotIn) for op in node.ops
        ):
            for operand in (node.left, *node.comparators):
                hits |= _names_in(operand, names, constants)
        elif isinstance(node, ast.Call) and call_name(node) in {"startswith", "endswith"}:
            for arg in node.args:
                for literal in (arg.elts if isinstance(arg, ast.Tuple) else [arg]):
                    if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                        prefix = _PREFIX.match(literal.value.lower())
                        if prefix and prefix.group(0).rstrip("_") in names:
                            hits.add(prefix.group(0).rstrip("_"))
    return hits


def _scoped_nodes(tree: ast.Module) -> Iterable[tuple[str, ast.AST]]:
    stack: list[tuple[str, ast.AST]] = [("<module>", tree)]
    while stack:
        scope, node = stack.pop()
        yield scope, node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = child.name if scope == "<module>" else f"{scope}.{child.name}"
                stack.append((inner, child))
            else:
                stack.append((scope, child))


def _branch_sites(tree: ast.Module) -> Iterable[tuple[str, str, ast.AST]]:
    for scope, node in _scoped_nodes(tree):
        if isinstance(node, ast.If | ast.IfExp | ast.While):
            yield scope, "test", node.test
        elif isinstance(node, ast.comprehension):
            yield from ((scope, "test", test) for test in node.ifs)
        elif isinstance(node, ast.match_case):
            yield scope, "case", node.pattern
        elif isinstance(node, ast.Dict):
            yield from ((scope, "key", key) for key in node.keys if key is not None)


def _pattern_names(pattern: ast.AST, names: frozenset[str], constants: frozenset[str]) -> set[str]:
    hits = set()
    for node in ast.walk(pattern):
        if isinstance(node, ast.MatchValue):
            hits |= _names_in(node.value, names, constants)
    return hits


def _site_hits(kind: str, node: ast.AST, names: frozenset[str], constants: frozenset[str]) -> set[str]:
    if kind == "case":
        return _pattern_names(node, names, constants)
    if kind == "key":
        return _names_in(node, names, constants)
    return _special_cases(node, names, constants)


def _site_text(kind: str, node: ast.AST) -> str:
    text = ast.unparse(node)
    return {"case": f"case {text}", "key": f"{{{text}: ...}}"}.get(kind, text)


def engine_branches(index: ModuleIndex, modules: Iterable[str]) -> Counter[str]:
    names = vocabulary(index)
    constants = named_constants(index, names)
    sites: Counter[str] = Counter()
    for module in modules:
        for scope, kind, node in _branch_sites(index.trees[module]):
            if _site_hits(kind, node, names, constants):
                sites[f"{index.paths[module]}::{scope}: {_site_text(kind, node)}"] += 1
    return sites
