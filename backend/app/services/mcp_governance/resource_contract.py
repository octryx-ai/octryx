"""Contract rules of mirrored MCP resources and prompts: what is addressable and which public contract is
stored."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..mcp_capability_contract import is_ambiguous_mcp_identifier
from ..redaction_policy import redact_secret_text
from .resource_credentials import mcp_resource_text_credential_finding
from .resource_identity import (
    MCP_PROMPT_KIND,
    MCP_PROMPT_SOURCE_ENTITY_TYPE,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_SOURCE_ENTITY_TYPE,
    mcp_prompt_binding_key,
    mcp_resource_binding_key,
    mcp_resource_server_marker_key,
)

MAX_MCP_RESOURCE_URI_CHARS = 1024
_MAX_DESCRIPTION_CHARS = 500
_MAX_NAME_CHARS = 200
_MAX_MIME_TYPE_CHARS = 120
_MAX_PROMPT_ARGUMENTS = 50
# Persisted identifier bounds, from the existing columns: ``capability_types.key``
# / ``workspace_capability_bindings.binding_key`` and ``display_name`` are
# ``String(200)``, ``source_entity_id`` is ``String(120)``.
_MAX_BINDING_KEY_CHARS = 200
_MAX_DISPLAY_NAME_CHARS = 200
_MAX_SOURCE_ENTITY_ID_CHARS = 120


@dataclass(frozen=True, slots=True)
class DiscoveredMcpResource:
    governed_uri: str
    identity: str
    name: str
    description: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class RejectedMcpMirrorEntry:
    # ``reason`` never carries provider text, a URI or an identifier; a refused item keeps its ``binding_key`` so it is
    # not marked missing.

    reason: str
    binding_key: str = ""

    @property
    def label(self) -> str:
        return f"[{self.reason}]"


@dataclass(frozen=True, slots=True)
class DiscoveredMcpPrompt:
    name: str
    description: str
    arguments: tuple[dict[str, Any], ...]


def mcp_resource_server_error(server_name: str) -> str | None:
    # ``:`` would make the catalog key prefix ambiguous and ``__`` the approval subject key.
    if is_ambiguous_mcp_identifier(server_name):
        return "MCP server name must not contain ':' or '__' to own a governed resource catalog"
    marker_length = max(
        len(mcp_resource_server_marker_key(kind, server_name)) for kind in (MCP_RESOURCE_KIND, MCP_PROMPT_KIND)
    )
    if marker_length > _MAX_BINDING_KEY_CHARS or len(str(server_name or "")) > _MAX_SOURCE_ENTITY_ID_CHARS:
        return "MCP server name is too long to be recorded as a workspace resource identifier"
    if len(mcp_resource_binding_key(server_name, "0" * 40)) > _MAX_BINDING_KEY_CHARS:
        return "MCP server name is too long to be recorded as a workspace resource identifier"
    return None


def normalize_mcp_resource_text(value: Any, *, max_chars: int = _MAX_DESCRIPTION_CHARS) -> str:
    return redact_secret_text(value, max_chars=max_chars)


def prompt_source_entity_id(server_name: str, prompt_name: str) -> str:
    return f"{server_name}:{prompt_name}"


def resource_display_name(server_name: str, governed_uri: str) -> str:
    return f"{server_name}/{governed_uri}"[:_MAX_DISPLAY_NAME_CHARS]


def prompt_display_name(server_name: str, prompt_name: str) -> str:
    return f"{server_name}/{prompt_name}"


def prompt_identifier_error(server_name: str, prompt_name: str) -> str | None:
    if not str(prompt_name or "").strip():
        return "empty_prompt_name"
    if is_ambiguous_mcp_identifier(prompt_name):
        return "ambiguous_prompt_name"
    if (
        len(mcp_prompt_binding_key(server_name, prompt_name)) > _MAX_BINDING_KEY_CHARS
        or len(prompt_source_entity_id(server_name, prompt_name)) > _MAX_SOURCE_ENTITY_ID_CHARS
        or len(prompt_display_name(server_name, prompt_name)) > _MAX_DISPLAY_NAME_CHARS
    ):
        return "prompt_identifier_too_long"
    return None


# Provider-controlled fields, named from a closed vocabulary so a rejection can
# say *which* field carried the finding without echoing any of its text.
# Every provider-controlled string a *persisted* contract can hold, across both
# kinds: a resource contract carries ``name``/``mimeType``, a prompt contract
# carries ``promptName`` and its argument list, and both carry ``description``.
CONTRACT_METADATA_FIELDS = ("name", "promptName", "description", "mimeType")


def metadata_credential_finding(fields: Sequence[tuple[str, Any]]) -> str:
    for field_name, value in fields:
        finding = mcp_resource_text_credential_finding(value)
        if finding:
            return f"{field_name}:{finding}"
    return ""


def _prompt_argument_metadata(arguments: Any) -> list[tuple[str, Any]]:
    fields: list[tuple[str, Any]] = []
    if not isinstance(arguments, (list, tuple)):
        return fields
    for argument in arguments[:_MAX_PROMPT_ARGUMENTS]:
        argument = argument if isinstance(argument, dict) else {}
        fields.append(("argumentName", argument.get("name")))
        fields.append(("argumentDescription", argument.get("description")))
    return fields


def mcp_resource_contract_credential_finding(contract: Any) -> str:
    # Rechecked with the current detector on every read, so a stored contract carrying a credential fails closed.
    mapping = contract if isinstance(contract, dict) else {}
    fields: list[tuple[str, Any]] = [(name, mapping.get(name)) for name in CONTRACT_METADATA_FIELDS]
    fields.extend(_prompt_argument_metadata(mapping.get("arguments")))
    return metadata_credential_finding(fields)


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcp_resource_contract(*, server_name: str, resource: DiscoveredMcpResource) -> dict[str, Any]:
    return {
        "sourceEntityType": MCP_RESOURCE_SOURCE_ENTITY_TYPE,
        "sourceEntityId": resource.identity,
        "serverName": server_name,
        "resourceIdentity": resource.identity,
        "resourceUri": resource.governed_uri,
        "name": resource.name,
        "description": resource.description,
        "mimeType": resource.mime_type,
        # Only what changes the answer is digested: a description edit must not park an approved item in review.
        "contractDigest": _digest({"mimeType": resource.mime_type}),
    }


def mcp_prompt_contract(*, server_name: str, prompt: DiscoveredMcpPrompt) -> dict[str, Any]:
    arguments = [dict(argument) for argument in prompt.arguments]
    return {
        "sourceEntityType": MCP_PROMPT_SOURCE_ENTITY_TYPE,
        "sourceEntityId": prompt_source_entity_id(server_name, prompt.name),
        "serverName": server_name,
        "promptName": prompt.name,
        "description": prompt.description,
        "arguments": arguments,
        "contractDigest": _digest(
            {"arguments": [{"name": item["name"], "required": item["required"]} for item in arguments]}
        ),
    }


__all__ = [
    "MAX_MCP_RESOURCE_URI_CHARS",
    "CONTRACT_METADATA_FIELDS",
    "DiscoveredMcpPrompt",
    "DiscoveredMcpResource",
    "RejectedMcpMirrorEntry",
    "mcp_prompt_contract",
    "mcp_resource_contract",
    "mcp_resource_contract_credential_finding",
    "metadata_credential_finding",
    "mcp_resource_server_error",
    "normalize_mcp_resource_text",
    "prompt_display_name",
    "prompt_identifier_error",
    "prompt_source_entity_id",
    "resource_display_name",
]
