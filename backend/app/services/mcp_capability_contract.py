"""Pure contract and identifier rules for mirrored MCP capabilities. Only a normalized public contract is stored."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .mcp_governance.capability_policy import (
    MCP_CAPABILITY_SOURCE_ENTITY_TYPE,
    mcp_capability_binding_key,
)
from .redaction_policy import redact_secret_text

_MAX_DESCRIPTION_CHARS = 500
_MAX_SCHEMA_PROPERTIES = 100

# Catalog keys are ``mcp-capability:{server}:{tool}`` and the direct dispatch name
# is ``mcp__{server}__{tool}``. Identifiers carrying these separators would make
# two different capabilities share one key, so they are rejected instead of
# silently mirrored into an ambiguous binding.
_AMBIGUOUS_IDENTIFIER_TOKENS = (":", "__")
# Persisted identifier bounds, from the existing columns:
# ``capability_types.key`` / ``workspace_capability_bindings.binding_key`` and
# ``display_name`` are ``String(200)``, ``source_entity_id`` is ``String(120)``.
# An identifier that does not fit is rejected before any DB write instead of
# being truncated into a different capability's key.
_MAX_BINDING_KEY_CHARS = 200
_MAX_DISPLAY_NAME_CHARS = 200
_MAX_SOURCE_ENTITY_ID_CHARS = 120


@dataclass(frozen=True, slots=True)
class DiscoveredMcpTool:
    name: str
    description: str
    input_schema: dict[str, Any]


def is_ambiguous_mcp_identifier(value: str) -> bool:
    return any(token in str(value or "") for token in _AMBIGUOUS_IDENTIFIER_TOKENS)


def capability_source_entity_id(server_name: str, tool_name: str) -> str:
    return f"{server_name}:{tool_name}"


def capability_display_name(server_name: str, tool_name: str) -> str:
    return f"{server_name}/{tool_name}"


def exceeds_mcp_identifier_limits(server_name: str, tool_name: str) -> bool:
    return (
        len(mcp_capability_binding_key(server_name, tool_name)) > _MAX_BINDING_KEY_CHARS
        or len(capability_source_entity_id(server_name, tool_name)) > _MAX_SOURCE_ENTITY_ID_CHARS
        or len(capability_display_name(server_name, tool_name)) > _MAX_DISPLAY_NAME_CHARS
    )


def server_identifier_error(server_name: str) -> str | None:
    if is_ambiguous_mcp_identifier(server_name):
        return "MCP server name must not contain ':' or '__' to stay addressable as a capability"
    if (
        len(server_name) > _MAX_SOURCE_ENTITY_ID_CHARS
        or exceeds_mcp_identifier_limits(server_name, "")
    ):
        return "MCP server name is too long to be recorded as a workspace capability identifier"
    return None


def discovered_mcp_tools(tools: Sequence[Any]) -> tuple[list[DiscoveredMcpTool], list[str]]:
    discovered: list[DiscoveredMcpTool] = []
    rejected: list[str] = []
    for tool in tools or []:
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        if is_ambiguous_mcp_identifier(name):
            rejected.append(name)
            continue
        raw_schema = getattr(tool, "input_schema", None)
        discovered.append(
            DiscoveredMcpTool(
                name=name,
                description=str(getattr(tool, "description", "") or ""),
                input_schema=raw_schema if isinstance(raw_schema, dict) else {},
            )
        )
    return discovered, rejected


def normalize_mcp_capability_description(value: Any) -> str:
    return redact_secret_text(value, max_chars=_MAX_DESCRIPTION_CHARS)


def normalize_mcp_capability_schema(input_schema: Any) -> dict[str, Any]:
    schema = input_schema if isinstance(input_schema, dict) else {}
    raw_properties = schema.get("properties")
    raw_properties = raw_properties if isinstance(raw_properties, dict) else {}
    required = sorted(
        {str(name).strip() for name in (schema.get("required") or []) if str(name).strip()}
        & {str(name).strip() for name in raw_properties}
    )
    properties: dict[str, Any] = {}
    for name in sorted(str(key).strip() for key in raw_properties if str(key).strip())[:_MAX_SCHEMA_PROPERTIES]:
        field = raw_properties.get(name)
        field = field if isinstance(field, dict) else {}
        normalized_field: dict[str, Any] = {"type": str(field.get("type") or "unknown")}
        description = normalize_mcp_capability_description(field.get("description"))
        if description:
            normalized_field["description"] = description
        enum_values = field.get("enum")
        if isinstance(enum_values, list) and enum_values:
            normalized_field["enum"] = [redact_secret_text(item, max_chars=120) for item in enum_values[:50]]
        properties[name] = normalized_field
    return {
        "type": str(schema.get("type") or "object"),
        "properties": properties,
        "required": required,
    }


def mcp_capability_schema_digest(normalized_schema: dict[str, Any]) -> str:
    canonical = json.dumps(normalized_schema, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcp_capability_contract(*, server_name: str, tool: DiscoveredMcpTool) -> dict[str, Any]:
    normalized_schema = normalize_mcp_capability_schema(tool.input_schema)
    return {
        "sourceEntityType": MCP_CAPABILITY_SOURCE_ENTITY_TYPE,
        "sourceEntityId": capability_source_entity_id(server_name, tool.name),
        "serverName": server_name,
        "toolName": tool.name,
        "description": normalize_mcp_capability_description(tool.description),
        "inputSchema": normalized_schema,
        "schemaDigest": mcp_capability_schema_digest(normalized_schema),
    }

__all__ = [
    "DiscoveredMcpTool",
    "capability_display_name",
    "capability_source_entity_id",
    "discovered_mcp_tools",
    "exceeds_mcp_identifier_limits",
    "is_ambiguous_mcp_identifier",
    "mcp_capability_contract",
    "mcp_capability_schema_digest",
    "normalize_mcp_capability_description",
    "normalize_mcp_capability_schema",
    "server_identifier_error",
]
