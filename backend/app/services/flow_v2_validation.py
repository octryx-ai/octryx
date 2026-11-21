from __future__ import annotations

from collections import defaultdict
from typing import Any

from .flow_node_registry import get_flow_node_contract
from .flow_orchestration.conditional_rules import (
    CONDITION_PROBLEM_TEXT,
    ROUTER_CONDITION_INVALID,
    ROUTER_RULE_INVALID,
    connection_condition_problem,
    router_rule_issues,
)
from .flow_orchestration.router_branches import ROUTER_BRANCH_UNCONNECTED, unconnected_router_branches
from .flow_v2_io_validation import _validate_flow_shape, _validate_io_mappings
from .flow_v2_validation_support import (
    _contract_can_start,
    _edge_value,
    _effective_schema,
    _is_empty_config_value,
    _scan_secret_values,
)


def validate_flow_definition_v2(definition: dict[str, Any]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    metadata = definition.get("metadata", {})
    nodes = definition.get("nodes")
    edges = definition.get("edges")
    io_mappings = definition.get("io_mappings", [])

    if metadata is not None and not isinstance(metadata, dict):
        errors.append({"code": "invalid_metadata", "message": "metadata must be an object."})
    if not isinstance(nodes, list) or not nodes:
        errors.append({"code": "missing_nodes", "message": "Flow v2 requires at least one node."})
        nodes = []
    if not isinstance(edges, list):
        errors.append({"code": "missing_edges", "message": "Flow v2 requires an edges list."})
        edges = []
    if io_mappings is not None and not isinstance(io_mappings, list):
        errors.append({"code": "invalid_io_mappings", "message": "io_mappings must be a list when provided."})
        io_mappings = []

    node_map = _validate_nodes(nodes, errors)
    _validate_edges(edges, node_map, errors, warnings)
    _validate_router_branches(edges, node_map, errors)
    _validate_io_mappings(io_mappings, node_map, errors)
    _validate_flow_shape(node_map, warnings)
    _scan_secret_values([], definition, errors)

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(node_map),
        "edge_count": len(edges),
        "node_types": sorted({str(node.get("type") or "") for node in node_map.values()}),
        "schema_version": "2.0",
    }


def _validate_nodes(nodes: list[Any], errors: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    node_map: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            errors.append({"code": "invalid_node", "message": "Every v2 node must be an object."})
            continue
        node_id = str(node.get("id") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if not node_id:
            errors.append({"code": "missing_node_id", "message": "Every v2 node requires an id."})
            continue
        if node_id in node_map:
            errors.append({"code": "duplicate_node_id", "message": f"Duplicate node id: {node_id}"})
        node_map[node_id] = node
        contract = get_flow_node_contract(node_type)
        if contract is None:
            errors.append(
                {
                    "code": "unsupported_node_type",
                    "message": f"Unsupported v2 node type for {node_id}: {node_type}",
                }
            )
            continue
        for key in ("config", "input_schema", "output_schema", "retry_policy", "timeout_policy", "budget_hints"):
            value = node.get(key, {})
            if value is not None and not isinstance(value, dict):
                errors.append({"code": "invalid_node_field", "message": f"{node_id}.{key} must be an object."})
        config = node.get("config") or {}
        if isinstance(config, dict):
            _validate_required_config(
                node_id,
                config,
                contract.required_config_keys,
                contract.required_config_any,
                errors,
            )
    return node_map


def _validate_required_config(
    node_id: str,
    config: dict[str, Any],
    required_keys: tuple[str, ...],
    required_any: tuple[str, ...],
    errors: list[dict[str, str]],
) -> None:
    for key in required_keys:
        if _is_empty_config_value(config.get(key)):
            errors.append({"code": "missing_required_config", "message": f"{node_id}.config.{key} is required."})
    if required_any and not any(not _is_empty_config_value(config.get(key)) for key in required_any):
        choices = ", ".join(required_any)
        errors.append(
            {
                "code": "missing_required_config",
                "message": f"{node_id}.config requires at least one of: {choices}.",
            }
        )


def _validate_edges(
    edges: list[Any],
    node_map: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> None:
    incoming_fields: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append({"code": "invalid_edge", "message": "Every v2 edge must be an object."})
            continue
        source_id = _edge_value(edge, "source_node_id", "from_node_id", "source", "from")
        target_id = _edge_value(edge, "target_node_id", "to_node_id", "target", "to")
        source = node_map.get(source_id)
        target = node_map.get(target_id)
        if source is None or target is None:
            errors.append(
                {
                    "code": "unknown_edge_node",
                    "message": f"Edge references unknown node: {source_id}->{target_id}",
                }
            )
            continue
        source_schema = _effective_schema(source, "output_schema")
        target_schema = _effective_schema(target, "input_schema")
        source_field = _edge_value(edge, "source_field", "source_handle", "from_output")
        target_field = _edge_value(edge, "target_field", "target_handle", "to_input")
        if source_field or target_field:
            _validate_field_edge(source_id, target_id, source_field, target_field, source_schema, target_schema, errors)
            if target_field:
                incoming_fields[target_id].add(target_field)
        else:
            missing = [key for key in target_schema if key not in source_schema]
            if missing:
                errors.append(
                    {
                        "code": "schema_contract_mismatch",
                        "message": f"{source_id}->{target_id} is missing output fields: {', '.join(missing)}",
                    }
                )
            incoming_fields[target_id].update(key for key in target_schema if key in source_schema)
        condition = edge.get("condition")
        if condition is not None and not isinstance(condition, (str, dict)):
            errors.append(
                {
                    "code": "invalid_edge_condition",
                    "message": f"{source_id}->{target_id}.condition must be a string or object.",
                }
            )
    for node_id, node in node_map.items():
        target_schema = _effective_schema(node, "input_schema")
        if target_schema and not incoming_fields[node_id] and not _contract_can_start(node):
            warnings.append(
                {
                    "code": "unmapped_node_input",
                    "message": f"{node_id} has input schema but no mapped incoming fields.",
                }
            )


def _validate_router_branches(
    edges: list[Any], node_map: dict[str, dict[str, Any]], errors: list[dict[str, str]]
) -> None:
    """Refuse what a router run would fail on: malformed rules or custom connection conditions,
    and a branch that provably runs nothing."""
    for node_id, node in node_map.items():
        if str(node.get("type") or "").strip() != "router":
            continue
        outgoing = [
            edge
            for edge in edges
            if isinstance(edge, dict)
            and _edge_value(edge, "source_node_id", "from_node_id", "source", "from") == node_id
        ]
        conditions = [edge.get("condition") for edge in outgoing]
        for issue in router_rule_issues(node.get("config")):
            errors.append(
                {
                    "code": ROUTER_RULE_INVALID,
                    "message": f"{node_id}.{issue.location}: {CONDITION_PROBLEM_TEXT[issue.problem]}",
                }
            )
        for edge in outgoing:
            problem = connection_condition_problem(edge.get("condition"))
            if problem:
                target = _edge_value(edge, "target_node_id", "to_node_id", "target", "to")
                errors.append(
                    {
                        "code": ROUTER_CONDITION_INVALID,
                        "message": f"{node_id}->{target}.condition: {CONDITION_PROBLEM_TEXT[problem]}",
                    }
                )
        unconnected = unconnected_router_branches(node.get("config"), conditions)
        if unconnected:
            errors.append(
                {
                    "code": ROUTER_BRANCH_UNCONNECTED,
                    "message": (
                        f"{node_id}: no connection runs for branch {', '.join(unconnected)}. Connect each branch, "
                        "or add a connection without a condition as the fallback."
                    ),
                }
            )


def _validate_field_edge(
    source_id: str,
    target_id: str,
    source_field: str,
    target_field: str,
    source_schema: dict[str, str],
    target_schema: dict[str, str],
    errors: list[dict[str, str]],
) -> None:
    if not source_field or not target_field:
        errors.append(
            {
                "code": "incomplete_field_mapping",
                "message": f"{source_id}->{target_id} requires source_field and target_field.",
            }
        )
        return
    if source_field not in source_schema:
        errors.append(
            {
                "code": "unknown_source_field",
                "message": f"{source_id}->{target_id} source field does not exist: {source_field}",
            }
        )
    if target_schema and target_field not in target_schema:
        errors.append(
            {
                "code": "unknown_target_field",
                "message": f"{source_id}->{target_id} target field does not exist: {target_field}",
            }
        )


__all__ = ["validate_flow_definition_v2"]
