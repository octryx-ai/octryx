"""Pure contract rules for mirrored MCP resources and prompts.

This module owns everything that can be decided without a database: which
resource URIs and prompt names are addressable and persistable, and what public
contract is stored for one of them. ``mcp_resource_catalog`` owns the writes,
``mcp_resource_policy`` owns the decision.

Only a normalized public contract is produced here:

- resources: server identity, the **governed** (redacted) URI plus its identity
  digest, a bounded redacted name and description, the declared media type, and a
  digest of that media type;
- prompts: server identity, prompt name, a bounded redacted description, the
  normalized argument list, and a digest of that argument contract.

The digests are deliberately narrow. A description changes often and must not
park an approved item in a drift review, so only what changes *what you get*
(``mimeType``) or *how you call it* (prompt arguments) is digested.

MCP connection configuration — commands, URLs, environment, headers, OAuth
material — is never read here and never stored. Neither is a resource URI that
carries a credential: ``mcp_resource_uri_credential_finding`` refuses it outright
rather than redacting and mirroring it, because a redacted URI is a URI the
platform could still hand to the transport. Such a resource is reported as a
rejection and never becomes addressable at all.

The same rule covers every *other* provider-controlled field, because the URI is
not the only place a remote server can put a credential. A resource or prompt
name, a description, a media type, and a prompt argument's name or description
all reach the model, the admin catalog, and the mirror report, and none of them
is sanitised by the generic redactor beyond URI userinfo. Each is checked
with ``mcp_resource_text_credential_finding`` before the contract is built; one
finding rejects the whole item, reported as ``[<field>:<finding>]`` — a closed
field name and a closed finding code, never the offending text.

Two rules govern how a refusal is reported, and both exist because the report is
persisted, returned to an admin API caller, and logged:

- **Credential inspection runs before identifier diagnostics.** A hostile item
  can be ambiguous, oversized, *and* credential-bearing at once; the credential is
  the fact that decides what may be said about it, so it is established first.
- **A rejection is a closed reason code and nothing else.** Never the provider's
  name, never its description, and never the governed URI — a governed URI is
  still a URI, naming an internal host, a bucket, or a database. Every entry in
  ``rejected_entries`` is therefore ``[<code>]`` or ``[<field>:<code>]``, bounded
  by construction rather than by truncation.

A rejection also carries the catalog key the item would own when it still has an
addressable identity (``RejectedMcpMirrorEntry.binding_key``). A refusal is not
evidence that the server stopped advertising the item, so the mirror needs that
key to keep an already-approved binding out of the missing-item lifecycle.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .mcp_capability_contract import is_ambiguous_mcp_identifier
from .mcp_resource_credentials import mcp_resource_text_credential_finding
from .mcp_resource_identity import (
    MCP_PROMPT_KIND,
    MCP_PROMPT_SOURCE_ENTITY_TYPE,
    MCP_RESOURCE_KIND,
    MCP_RESOURCE_SOURCE_ENTITY_TYPE,
    mcp_prompt_binding_key,
    mcp_resource_binding_key,
    mcp_resource_server_marker_key,
)
from .redaction_policy import redact_secret_text

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
    """The public part of one discovered MCP resource, decoupled from the client."""

    governed_uri: str
    identity: str
    name: str
    description: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class RejectedMcpMirrorEntry:
    """One provider item a mirror run refused, named by a closed reason code.

    ``reason`` is ``<code>`` or ``<field>:<code>`` from the closed vocabularies in
    this module and in ``mcp_resource_arguments``; it never contains provider
    text, a URI, or an identifier. ``binding_key`` is the catalog key the item
    would own when it still has an addressable identity — a credential in a
    *description* does not change a resource's identity — and ``""`` when it has
    none. The mirror uses that key to keep a refused item out of the missing-item
    lifecycle, because a refusal is not evidence that the server stopped
    advertising it.
    """

    reason: str
    binding_key: str = ""

    @property
    def label(self) -> str:
        """The bounded, bracketed form one rejection is reported under."""
        return f"[{self.reason}]"


@dataclass(frozen=True, slots=True)
class DiscoveredMcpPrompt:
    """The public part of one discovered MCP prompt, decoupled from the client."""

    name: str
    description: str
    arguments: tuple[dict[str, Any], ...]


def mcp_resource_server_error(server_name: str) -> str | None:
    """Return why a server name cannot own a governed catalog, or ``None``.

    ``:`` would make the catalog key prefix ambiguous and ``__`` would make the
    approval subject key ambiguous, so both are rejected — the same rule the
    mirrored tool catalog applies.
    """
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
    """Return a bounded, secret-redacted display string."""
    return redact_secret_text(value, max_chars=max_chars)


def prompt_source_entity_id(server_name: str, prompt_name: str) -> str:
    """Return the persisted source-entity id of one mirrored prompt."""
    return f"{server_name}:{prompt_name}"


def resource_display_name(server_name: str, governed_uri: str) -> str:
    """Return the bounded catalog display name of one mirrored resource."""
    return f"{server_name}/{governed_uri}"[:_MAX_DISPLAY_NAME_CHARS]


def prompt_display_name(server_name: str, prompt_name: str) -> str:
    """Return the catalog display name of one mirrored prompt."""
    return f"{server_name}/{prompt_name}"


def prompt_identifier_error(server_name: str, prompt_name: str) -> str | None:
    """Return why one prompt cannot be mirrored, or ``None`` when it can."""
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
    """Return ``"<field>:<finding>"`` for the first field that carries one."""
    for field_name, value in fields:
        finding = mcp_resource_text_credential_finding(value)
        if finding:
            return f"{field_name}:{finding}"
    return ""


def _prompt_argument_metadata(arguments: Any) -> list[tuple[str, Any]]:
    """Every provider-controlled string in a prompt's declared argument list."""
    fields: list[tuple[str, Any]] = []
    if not isinstance(arguments, (list, tuple)):
        return fields
    for argument in arguments[:_MAX_PROMPT_ARGUMENTS]:
        argument = argument if isinstance(argument, dict) else {}
        fields.append(("argumentName", argument.get("name")))
        fields.append(("argumentDescription", argument.get("description")))
    return fields


def mcp_resource_contract_credential_finding(contract: Any) -> str:
    """Return the credential finding a *persisted* contract carries under today's detector, or ``""``.

    The mirror refuses such an item when it writes it; the decision checks the stored contract again on every read
    with the current credential detector, so a stored binding is judged by the rules in force when it is used, and a
    contract that carries a credential fails closed rather than be published.
    """
    mapping = contract if isinstance(contract, dict) else {}
    fields: list[tuple[str, Any]] = [(name, mapping.get(name)) for name in CONTRACT_METADATA_FIELDS]
    fields.extend(_prompt_argument_metadata(mapping.get("arguments")))
    return metadata_credential_finding(fields)


def _digest(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def mcp_resource_contract(*, server_name: str, resource: DiscoveredMcpResource) -> dict[str, Any]:
    """Build the persisted public contract for one mirrored MCP resource."""
    return {
        "sourceEntityType": MCP_RESOURCE_SOURCE_ENTITY_TYPE,
        "sourceEntityId": resource.identity,
        "serverName": server_name,
        "resourceIdentity": resource.identity,
        "resourceUri": resource.governed_uri,
        "name": resource.name,
        "description": resource.description,
        "mimeType": resource.mime_type,
        "contractDigest": _digest({"mimeType": resource.mime_type}),
    }


def mcp_prompt_contract(*, server_name: str, prompt: DiscoveredMcpPrompt) -> dict[str, Any]:
    """Build the persisted public contract for one mirrored MCP prompt."""
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
