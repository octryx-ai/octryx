"""Static detector for writers of the Agent Definition aggregate."""

from __future__ import annotations

import ast
import pathlib

from tests.services.agents.agent_definition_writer_rows_support import (
    AGGREGATE_CLASSES,
    _assigned_names,
    _root_name,
    _traverses_aggregate_relationship,
    aggregate_column_names,
    aggregate_relationship_names,
    relationship_row_names,
    row_bearing_names,
)

#: Modules that *define* the aggregate or only re-export it. They are not writers.
DECLARATION_MODULES = frozenset(
    {
        "app.models.agent.agent_definition",
        "app.models.agent.__init__",
        "app.models.__init__",
    }
)

#: Core statement constructors that write without loading a row.
_BULK_STATEMENTS = frozenset({"update", "insert", "delete"})

#: Session methods that remove or re-attach a mapped instance. ``add`` is left out
#: on purpose: a row it could add was either constructed or mutated here anyway, and
#: ``add`` collides with ``set.add`` on a set of row ids.
_SESSION_WRITES = frozenset({"delete", "merge"})

REASON_CONSTRUCTS = "constructs"
REASON_MUTATES = "mutates"
REASON_SETATTR = "setattr"
REASON_BULK_WRITE = "bulk_write"
REASON_SESSION_DELETE = "session_delete"
REASON_RELATIONSHIP_WRITE = "relationship_write"


def _scopes(tree: ast.Module) -> list[ast.AST]:
    scopes: list[ast.AST] = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    module_level = [
        statement
        for statement in tree.body
        if not isinstance(
            statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    ]
    scopes.append(ast.Module(body=module_level, type_ignores=[]))
    return scopes


def _scan_aggregate_references(tree: ast.AST) -> set[str]:
    reasons: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in AGGREGATE_CLASSES:
            reasons.add(REASON_CONSTRUCTS)
            continue
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in _BULK_STATEMENTS and any(
            isinstance(arg, ast.Name) and arg.id in AGGREGATE_CLASSES for arg in node.args
        ):
            reasons.add(REASON_BULK_WRITE)
    return reasons


def _aggregate_field_names(scope: ast.AST) -> set[str]:
    columns = aggregate_column_names()
    bound: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            continue
        literals = [
            element.value
            for element in node.iter.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
        if literals and len(literals) == len(node.iter.elts) and set(literals) <= columns:
            bound.update(_assigned_names(node.target))
    return bound


def _is_aggregate_field(argument: ast.expr | None, field_names: set[str]) -> bool:
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value in aggregate_column_names()
    return isinstance(argument, ast.Name) and argument.id in field_names


def _scan_scope(scope: ast.AST, rows: set[str], related: set[str]) -> set[str]:
    reasons: set[str] = set()
    field_names = _aggregate_field_names(scope)
    known = rows | related
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "setattr" and node.args:
                if _root_name(node.args[0]) in known or _is_aggregate_field(
                    node.args[1] if len(node.args) > 1 else None, field_names
                ):
                    reasons.add(REASON_SETATTR)
            elif getattr(func, "attr", "") in _SESSION_WRITES and any(
                _root_name(arg) in known for arg in node.args
            ):
                reasons.add(REASON_SESSION_DELETE)
            continue

        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            for element in target.elts if isinstance(target, ast.Tuple) else [target]:
                if not isinstance(element, ast.Attribute):
                    continue
                if _root_name(element) in rows:
                    reasons.add(REASON_MUTATES)
                elif element.attr in aggregate_column_names() and (
                    _root_name(element) in related
                    or _traverses_aggregate_relationship(element.value)
                ):
                    reasons.add(REASON_RELATIONSHIP_WRITE)
    return reasons


def _scan_triggers() -> frozenset[str]:
    return frozenset(AGGREGATE_CLASSES) | {
        f".{name}" for name in aggregate_relationship_names()
    }


def scan_source(source: str, *, filename: str = "<memory>") -> set[str]:
    if not any(token in source for token in _scan_triggers()):
        return set()
    tree = ast.parse(source, filename=filename)
    reasons = _scan_aggregate_references(tree)
    for scope in _scopes(tree):
        reasons |= _scan_scope(
            scope, row_bearing_names(scope), relationship_row_names(scope)
        )
    return reasons


def module_name(path: pathlib.Path, app_root: pathlib.Path) -> str:
    return ".".join(path.relative_to(app_root.parent).with_suffix("").parts)


def scan_app_tree(app_root: pathlib.Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(app_root.rglob("*.py")):
        name = module_name(path, app_root)
        if name in DECLARATION_MODULES:
            continue
        reasons = scan_source(path.read_text(encoding="utf-8"), filename=str(path))
        if reasons:
            found[name] = reasons
    return found


__all__ = [
    "AGGREGATE_CLASSES",
    "aggregate_column_names",
    "aggregate_relationship_names",
    "DECLARATION_MODULES",
    "REASON_BULK_WRITE",
    "REASON_CONSTRUCTS",
    "REASON_MUTATES",
    "REASON_RELATIONSHIP_WRITE",
    "REASON_SESSION_DELETE",
    "REASON_SETATTR",
    "module_name",
    "relationship_row_names",
    "row_bearing_names",
    "scan_app_tree",
    "scan_source",
]
