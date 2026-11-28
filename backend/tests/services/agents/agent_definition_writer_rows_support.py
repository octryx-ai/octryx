"""Row inference of the Agent Definition writer detector (``agent_definition_writer_scan_support``)."""

from __future__ import annotations

import ast
import functools
from collections.abc import Callable

AGGREGATE_CLASSES = frozenset({"AgentDefinition", "AgentStep"})


@functools.cache
def aggregate_column_names() -> frozenset[str]:
    from app.models import AgentDefinition, AgentStep

    return frozenset(
        column.key
        for model in (AgentDefinition, AgentStep)
        for column in model.__table__.columns
    )

@functools.cache
def aggregate_relationship_names() -> frozenset[str]:
    from app.db import Base
    from app.models import AgentDefinition  # noqa: F401  (ensures mappers are configured)

    return frozenset(
        relationship.key
        for mapper in Base.registry.mappers
        for relationship in mapper.relationships
        if relationship.mapper.class_.__name__ in AGGREGATE_CLASSES
    )


def _root_name(node: ast.expr) -> str | None:
    current: ast.expr | None = node
    while current is not None:
        if isinstance(current, ast.Name):
            return current.id
        if isinstance(current, (ast.Attribute, ast.Subscript, ast.Starred)):
            current = current.value
        elif isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Await):
            current = current.value
        else:
            return None
    return None


def _mentions_aggregate(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Name) and child.id in AGGREGATE_CLASSES
        for child in ast.walk(node)
    )


def _is_row_producer(value: ast.expr) -> bool:
    for child in ast.walk(value):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id in AGGREGATE_CLASSES:
            return True
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name in {"select", "get", "query"} and any(
            isinstance(arg, ast.Name) and arg.id in AGGREGATE_CLASSES for arg in child.args
        ):
            return True
    return False


def _annotation_names_aggregate(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return any(name in annotation.value for name in AGGREGATE_CLASSES)
    return _mentions_aggregate(annotation)


def _assigned_names(target: ast.expr) -> list[str]:
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _assigned_names(element)]
    if isinstance(target, ast.Starred):
        return _assigned_names(target.value)
    return []


def _traverses_aggregate_relationship(node: ast.AST) -> bool:
    names = aggregate_relationship_names()
    return any(
        isinstance(child, ast.Attribute) and child.attr in names
        for child in ast.walk(node)
    )


def _propagate(
    tree: ast.AST,
    *,
    is_producer: Callable[[ast.expr], bool],
    seed: set[str],
) -> set[str]:
    names = set(seed)
    while True:
        before = len(names)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                # Only a *copy* of a row propagates (``x = row``, ``x = row.steps``,
                # ``x = list(rows)``). Any expression merely mentioning a row — a
                # snapshot built from it, a serialized payload — does not, or every
                # reader of the aggregate would count as a writer.
                if is_producer(node.value) or _root_name(node.value) in names:
                    for target in targets:
                        names.update(_assigned_names(target))
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                # Iteration is matched more loosely: ``enumerate(rows)`` and
                # ``zip(rows, ...)`` still hand out rows.
                iterated = node.iter
                if is_producer(iterated) or _refers_to(iterated, names):
                    names.update(_assigned_names(node.target))
        if len(names) == before:
            return names


def _annotated_row_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and _annotation_names_aggregate(node.annotation):
            names.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and _annotation_names_aggregate(node.annotation):
            names.update(_assigned_names(node.target))
    return names


def row_bearing_names(tree: ast.AST) -> set[str]:
    return _propagate(
        tree, is_producer=_is_row_producer, seed=_annotated_row_names(tree)
    )


def relationship_row_names(tree: ast.AST) -> set[str]:
    return _propagate(
        tree, is_producer=_traverses_aggregate_relationship, seed=set()
    ) - row_bearing_names(tree)


def _refers_to(node: ast.AST, names: set[str]) -> bool:
    return any(
        isinstance(child, ast.Name) and child.id in names for child in ast.walk(node)
    )
