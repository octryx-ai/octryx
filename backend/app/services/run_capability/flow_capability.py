"""The capability class a flow definition declares."""

from __future__ import annotations

from typing import Any

from .declared import (
    DECLARED_CAPABILITY_KEY,
    DECLARED_RUN_CAPABILITY_METADATA_KEY,
    SOURCE_FLOW_DEFINITION,
    DeclaredRunCapability,
    declared_run_capability,
    validate_declared_capability_class,
)


def flow_definition_tool_names(definition: dict[str, Any] | None) -> list[str]:
    names: list[str] = []
    for node in (definition or {}).get("nodes") or []:
        config = node.get("config") if isinstance(node, dict) and isinstance(node.get("config"), dict) else {}
        for key in ("tool", "tool_name"):
            if str(config.get(key) or "").strip():
                names.append(str(config[key]).strip())
        allowed = config.get("allowed_tools")
        if isinstance(allowed, list):
            names.extend(str(item).strip() for item in allowed if str(item or "").strip())
    return sorted(set(names))


def flow_declared_capability(definition: dict[str, Any] | None) -> DeclaredRunCapability:
    return declared_run_capability((definition or {}).get(DECLARED_CAPABILITY_KEY), source=SOURCE_FLOW_DEFINITION)


def flow_session_capability_metadata(definition: dict[str, Any] | None) -> dict[str, Any]:
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: flow_declared_capability(definition).to_metadata()}


def validate_flow_capability_class(definition: dict[str, Any]) -> list[dict[str, str]]:
    return validate_declared_capability_class(
        definition.get(DECLARED_CAPABILITY_KEY),
        tool_names=flow_definition_tool_names(definition),
        subject="Flow definition",
    )


__all__ = [
    "flow_declared_capability",
    "flow_definition_tool_names",
    "flow_session_capability_metadata",
    "validate_flow_capability_class",
]
