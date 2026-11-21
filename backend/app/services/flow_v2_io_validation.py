"""io_mappings and flow shape checks of the flow v2 validation."""

from __future__ import annotations

from typing import Any

from .flow_v2_validation_support import _contract_can_end, _contract_can_start, _effective_schema


def _validate_io_mappings(
    io_mappings: list[Any],
    node_map: dict[str, dict[str, Any]],
    errors: list[dict[str, str]],
) -> None:
    for index, mapping in enumerate(io_mappings):
        if not isinstance(mapping, dict):
            errors.append({"code": "invalid_io_mapping", "message": f"io_mappings[{index}] must be an object."})
            continue
        source = str(mapping.get("source") or "").strip()
        target = str(mapping.get("target") or "").strip()
        if not source or not target:
            errors.append(
                {
                    "code": "invalid_io_mapping",
                    "message": f"io_mappings[{index}] requires source and target.",
                }
            )
            continue
        _validate_field_path(source, node_map, "source", index, errors)
        _validate_field_path(target, node_map, "target", index, errors)


def _validate_field_path(
    value: str,
    node_map: dict[str, dict[str, Any]],
    side: str,
    index: int,
    errors: list[dict[str, str]],
) -> None:
    if "." not in value:
        errors.append(
            {
                "code": "invalid_field_path",
                "message": f"io_mappings[{index}].{side} must use node.field syntax.",
            }
        )
        return
    node_id, field_name = value.split(".", 1)
    if node_id in {"$input", "$output"}:
        return
    node = node_map.get(node_id)
    if node is None:
        errors.append(
            {
                "code": "invalid_field_path",
                "message": f"io_mappings[{index}].{side} references unknown node: {node_id}",
            }
        )
        return
    schema_key = "output_schema" if side == "source" else "input_schema"
    schema = _effective_schema(node, schema_key)
    if schema and field_name not in schema:
        errors.append(
            {
                "code": "invalid_field_path",
                "message": f"io_mappings[{index}].{side} references unknown field: {value}",
            }
        )


def _validate_flow_shape(node_map: dict[str, dict[str, Any]], warnings: list[dict[str, str]]) -> None:
    if node_map and not any(_contract_can_start(node) for node in node_map.values()):
        warnings.append({"code": "missing_start_node", "message": "Flow v2 has no node that can start a flow."})
    if node_map and not any(_contract_can_end(node) for node in node_map.values()):
        warnings.append({"code": "missing_end_node", "message": "Flow v2 has no node that can end a flow."})
