"""The contract of one Flow Builder node type and the schema helper its entries use.

:mod:`app.services.flow_node_registry` builds the node registry from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FlowNodeContract:
    type: str
    display_name: str
    category: str
    description: str
    config_schema: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, str] = field(default_factory=dict)
    output_schema: dict[str, str] = field(default_factory=dict)
    can_start: bool = False
    can_end: bool = False
    can_pause: bool = False
    calls_tools: bool = False
    calls_llm: bool = False
    required_config_keys: tuple[str, ...] = ()
    required_config_any: tuple[str, ...] = ()
    security_requirements: tuple[str, ...] = ()
    project_visibility_implications: tuple[str, ...] = ()

    def serialize(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "config_schema": dict(self.config_schema),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "can_start": self.can_start,
            "can_end": self.can_end,
            "can_pause": self.can_pause,
            "calls_tools": self.calls_tools,
            "calls_llm": self.calls_llm,
            "required_config_keys": list(self.required_config_keys),
            "required_config_any": list(self.required_config_any),
            "security_requirements": list(self.security_requirements),
            "project_visibility_implications": list(self.project_visibility_implications),
        }


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": True,
    }
