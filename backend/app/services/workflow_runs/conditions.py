"""Decisions: a condition routes on an earlier result or on a field of the run's work item."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from .graph import (
    DECISION_CHECK_FIELD,
    DECISION_CHECK_RESULT,
    NO,
    NODE_DECISION,
    NODE_PHASE,
    OTHERWISE,
    YES,
    PhasedGraph,
    PhasedNode,
    route_values,
)
from .work_item_fields import KIND_NUMBER, OPERATORS_BY_KIND, WORK_ITEM_FIELDS, compare, field_value, work_item_field

RESULT_VALUES_KEY = "result_values"
_RESULT_VALUE = re.compile(r"^[a-z][a-z0-9_]*$")


class ConditionUnavailableError(Exception):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def decision_check(node: PhasedNode) -> str:
    return _text(node.config.get("check")) or DECISION_CHECK_RESULT


def declared_result_values(config: dict[str, Any]) -> tuple[str, ...]:
    raw = config.get(RESULT_VALUES_KEY)
    return tuple(_text(item) for item in raw if _text(item)) if isinstance(raw, list) else ()


def phase_result_values(node: PhasedNode | None) -> tuple[str, ...]:
    return declared_result_values(node.config) if node is not None and node.kind == NODE_PHASE else ()


def result_values_errors(node: PhasedNode) -> list[dict[str, str]]:
    if RESULT_VALUES_KEY not in node.config:
        return []
    raw = node.config[RESULT_VALUES_KEY]
    if not isinstance(raw, list) or not all(isinstance(item, str) and _RESULT_VALUE.match(item) for item in raw):
        return [_error("phase_result_values", f"Phase '{node.id}': result_values lists snake_case names "
                                              "(lower case letters, digits and _).")]
    if len(set(raw)) != len(raw):
        return [_error("phase_result_values", f"Phase '{node.id}': each result value appears once.")]
    if OTHERWISE in raw:
        return [_error("phase_result_values", f"Phase '{node.id}': '{OTHERWISE}' is reserved for a condition's "
                                              "fallback route.")]
    return []


def source_values(source: PhasedNode, graph: PhasedGraph) -> frozenset[str] | None:
    if source.kind == NODE_PHASE:
        return frozenset(phase_result_values(source)) or None
    values = route_values(source, graph)
    return None if values is None else values - {OTHERWISE}


def _routed(graph: PhasedGraph, node: PhasedNode) -> set[str | None]:
    return {edge.when for edge in graph.exits(node.id)}


def _field_errors(node: PhasedNode, graph: PhasedGraph) -> list[dict[str, str]]:
    config = node.config
    field = work_item_field(config.get("field"))
    if field is None:
        known = ", ".join(item.key for item in WORK_ITEM_FIELDS)
        return [_error("decision_field", f"Decision '{node.id}' compares an unknown field "
                                         f"'{_text(config.get('field'))}' (one of: {known}).")]
    errors: list[dict[str, str]] = []
    operators = OPERATORS_BY_KIND[field.kind]
    if _text(config.get("operator")) not in operators:
        errors.append(_error("decision_operator", f"Decision '{node.id}' compares {field.key} with one of: "
                                                  f"{', '.join(operators)}."))
    value = config.get("value")
    if field.kind == KIND_NUMBER:
        if isinstance(value, bool) or not isinstance(value, int | float):
            errors.append(_error("decision_value", f"Decision '{node.id}' compares {field.key} with a number."))
    elif not isinstance(value, str) or not value.strip():
        errors.append(_error("decision_value", f"Decision '{node.id}' needs the value {field.key} is compared with."))
    elif field.values and value.strip() not in field.values:
        errors.append(_error("decision_value", f"Decision '{node.id}': {field.key} is one of "
                                               f"{', '.join(field.values)}."))
    missing = [value for value in (YES, NO) if value not in _routed(graph, node)]
    if missing:
        errors.append(_error("decision_unrouted", f"Decision '{node.id}' needs a route for both yes and no "
                                                  f"({', '.join(missing)} has none)."))
    return errors


def decision_errors(node: PhasedNode, graph: PhasedGraph) -> list[dict[str, str]]:
    check = decision_check(node)
    if check == DECISION_CHECK_FIELD:
        return _field_errors(node, graph)
    if check != DECISION_CHECK_RESULT:
        return [_error("decision_check", f"Decision '{node.id}' checks '{DECISION_CHECK_RESULT}' (an earlier "
                                         f"result) or '{DECISION_CHECK_FIELD}' (a work item field).")]
    source = graph.nodes.get(_text(node.config.get("source")))
    if source is None or source.id == node.id:
        return [_error("decision_source", f"Decision '{node.id}' routes on an unknown node.")]
    allowed = source_values(source, graph)
    if allowed is None and source.kind == NODE_PHASE:
        return [_error("decision_source", f"Decision '{node.id}' routes on phase '{source.id}', which declares no "
                                          "result_values.")]
    options = frozenset(_text(item) for item in node.config.get("options") or [] if _text(item))
    if not options or allowed is None or not options <= allowed:
        return [_error("decision_options", f"Decision '{node.id}' options must be values of '{source.id}'.")]
    routed = _routed(graph, node)
    unrouted = sorted(allowed - routed)
    if OTHERWISE not in routed and unrouted:
        return [_error("decision_unrouted", f"Decision '{node.id}': every value needs a route or an otherwise "
                                            f"({', '.join(unrouted)} has none).")]
    return []


async def decision_route(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, node: PhasedNode) -> Any:
    if node.kind != NODE_DECISION:
        raise ValueError(node.id)
    if decision_check(node) == DECISION_CHECK_FIELD:
        field = work_item_field(node.config.get("field"))
        if field is None:
            raise ConditionUnavailableError(f"Decision '{node.id}' compares an unknown field.")
        item = None
        if field.column:
            from ...models.runtime.secure_work import WorkItem

            item = await db.get(WorkItem, run.work_item_id) if run.work_item_id else None
            if item is None:
                raise ConditionUnavailableError(f"Decision '{node.id}' compares the work item's {field.key}, but "
                                                "the run has no work item.")
        actual = field_value(field, run, item)
        return YES if compare(field, _text(node.config.get("operator")), actual, node.config.get("value")) else NO
    value = dict(dict(run.context or {}).get("results") or {}).get(_text(node.config.get("source")))
    options = {_text(item) for item in node.config.get("options") or [] if _text(item)}
    exits = graph.exits(node.id)
    if value is not None and str(value) in options and any(edge.when == str(value) for edge in exits):
        return value
    if any(edge.when == OTHERWISE for edge in exits):
        return OTHERWISE
    return value  # no route: the engine fails the run with the value it could not route


__all__ = [
    "RESULT_VALUES_KEY",
    "ConditionUnavailableError",
    "decision_check",
    "decision_errors",
    "decision_route",
    "declared_result_values",
    "phase_result_values",
    "result_values_errors",
    "source_values",
]
