"""The capability class a flow definition declares.

A flow never picks a workflow; it declares its class as data on the definition
(``definition_json.capability_class``). The flow's tool nodes dispatch under that class, and the
declaration is validated with the definition, like a workflow definition's class: an unsupported
value is refused, and so is a tool node whose tool needs more than the declared class (or than
``read_only`` when the flow declares nothing). The flow session the runner creates records the
declaration too, so an agent turn in that session builds its execution profile from the flow.
"""

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
    """Every tool a flow's nodes name: ``config.tool`` / ``config.tool_name`` and ``config.allowed_tools``."""
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
    """The class the flow declares; a flow that declares nothing runs ``read_only``."""
    return declared_run_capability((definition or {}).get(DECLARED_CAPABILITY_KEY), source=SOURCE_FLOW_DEFINITION)


def flow_session_capability_metadata(definition: dict[str, Any] | None) -> dict[str, Any]:
    """The flow session metadata that makes its ``run_agent`` turns resolve the flow's declared class."""
    return {DECLARED_RUN_CAPABILITY_METADATA_KEY: flow_declared_capability(definition).to_metadata()}


def validate_flow_capability_class(definition: dict[str, Any]) -> list[dict[str, str]]:
    """Errors for the flow's declared class and the tools its nodes use."""
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
