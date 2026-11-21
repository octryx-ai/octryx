"""Static detector for writers of the Agent Definition aggregate.

``test_agent_definition_writer_inventory.py`` uses this to prove that the inventory
in ``app.services.agent_definition_writers`` is complete. It lives in its own module
because the detector itself needs negative tests: a guard that silently fails to
recognise a write is worse than no guard, so every escape pattern it must catch is
asserted against a synthetic source in that test module.

What counts as writing the aggregate:

``constructs``
    ``AgentDefinition(...)`` / ``AgentStep(...)``.
``mutates``
    ``<row>.<field> = ...`` on a name this module obtained a row through — including
    through a subscript (``steps[i].position = ...``) or a loop variable.
``setattr``
    ``setattr(<row>, ...)``, the reflective form of the same thing — matched either
    by the row-bearing name or by the *field* being an aggregate column, which is
    what catches a row handed out by an unannotated helper in another module.
``bulk_write``
    ``update(AgentDefinition)`` / ``insert(...)`` / ``delete(...)`` — a Core statement
    that never loads a row, so no ORM-level detection would see it.
``session_delete``
    ``db.delete(<row>)`` / ``db.merge(<row>)`` — a write that neither constructs nor
    mutates, so nothing else would catch it.
``relationship_write``
    a write reached by traversing a *relationship* onto the aggregate —
    ``for agent in group.agents: agent.group_id = None`` — in a module that never
    names ``AgentDefinition`` or ``AgentStep`` at all. This is how
    e.g. ``agent_group.crud.delete_agent_group`` clears the checksum-bearing ``group_id`` of every member
    definition without naming an aggregate class, so a scan that stopped at the first line would miss it.

Row-bearing names are inferred rather than hardcoded: a hardcoded name list is
exactly how a writer using its own local naming escapes the guard. Inference runs
**per function scope**, because a module-wide name set lets one function's ``result``
or ``agent`` make every other function in the file look like a writer.

The relationship rule is deliberately an over-approximation: the relationship
*names* come from the mappers, but a name can be shared with another model
(``Task.steps`` as well as ``AgentDefinition.steps``), and so can a column name
(``TaskStep.allowed_tools_json``). ``upsert_task_from_package`` therefore matches it
too — that module is a registered writer for its Agent Definition half anyway. The
bias is intentional: a false positive costs one registration or one rename, a false
negative costs an ungoverned writer of the executed tool allow-list.

The aggregate's vocabulary and the row inference live in ``agent_definition_writer_rows_support``.
"""

from __future__ import annotations

import ast
import pathlib

from tests.agent_definition_writer_rows_support import (
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
    """Every function scope, plus the module's own non-function statements."""
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
    """Reasons that need no row inference: the aggregate class is named directly."""
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
    """Names bound by iterating a literal list of aggregate column names.

    ``for field in ("name", "goal", ...): setattr(agent, field, ...)`` is a real
    update in the tree, and the row it updates comes from an unannotated helper in
    another module — so the *field list* is the only static evidence available. All
    literals must be aggregate columns; a mixed list belongs to another model.
    """
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
    """Reasons that depend on which names in *scope* hold a row.

    *rows* are names proven to hold an aggregate row; *related* are names that only
    reached one through a relationship traversal, so a write through them additionally
    has to name an aggregate column.
    """
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
    """Cheap textual pre-filter: what a source must mention to be worth parsing.

    The aggregate class names alone were not enough — a relationship traversal writes
    the aggregate without naming it — so an attribute access on any relationship that
    yields aggregate rows also triggers a parse.
    """
    return frozenset(AGGREGATE_CLASSES) | {
        f".{name}" for name in aggregate_relationship_names()
    }


def scan_source(source: str, *, filename: str = "<memory>") -> set[str]:
    """Reasons *source* is a writer of the aggregate; empty when it is not one."""
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
    """Map module name -> reasons, for every module under *app_root* that writes."""
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
