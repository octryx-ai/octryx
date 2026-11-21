"""Node contract lookups, edge readers and the raw-secret scan shared by the flow v2 validation."""

from __future__ import annotations

import re
from typing import Any

from .flow_node_registry import get_flow_node_contract

SECRET_KEY_PATTERN = re.compile(r"(api[_-]?key|password|secret|token|credential|private[_-]?key)", re.IGNORECASE)
SECRET_REF_PATTERN = re.compile(r"^(secret|vault|stored-secret)://[A-Za-z0-9._:/@-]+$")


def _effective_schema(node: dict[str, Any], schema_key: str) -> dict[str, str]:
    value = node.get(schema_key)
    if isinstance(value, dict) and value:
        return {str(key): str(item) for key, item in value.items()}
    contract = get_flow_node_contract(str(node.get("type") or ""))
    if contract is None:
        return {}
    source = contract.output_schema if schema_key == "output_schema" else contract.input_schema
    return dict(source)


def _contract_can_start(node: dict[str, Any]) -> bool:
    contract = get_flow_node_contract(str(node.get("type") or ""))
    return bool(contract and contract.can_start)


def _contract_can_end(node: dict[str, Any]) -> bool:
    contract = get_flow_node_contract(str(node.get("type") or ""))
    return bool(contract and contract.can_end)


def _edge_value(edge: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(edge.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_empty_config_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _scan_secret_values(path: list[str], value: Any, errors: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if SECRET_KEY_PATTERN.search(str(key)) and isinstance(item, str) and not SECRET_REF_PATTERN.match(item):
                secret_path = "/".join(path + [str(key)])
                errors.append(
                    {
                        "code": "raw_secret_value",
                        "message": f"Secret-like field {secret_path} must reference a secure secret URI.",
                    }
                )
            _scan_secret_values(path + [str(key)], item, errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_secret_values(path + [str(index)], item, errors)
