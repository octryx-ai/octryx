"""Discovery side of the mirrored MCP resource contract.

Splits the resource and prompt objects an MCP client listed into the items a
mirror run may persist and the ones it refuses, by the rules in
``mcp_resource_contract``: credential inspection runs before any identifier
diagnostic, and a refusal is a closed reason code that never echoes provider text,
a URI, or an identifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .mcp_resource_contract import (
    _MAX_MIME_TYPE_CHARS,
    _MAX_NAME_CHARS,
    _MAX_PROMPT_ARGUMENTS,
    MAX_MCP_RESOURCE_URI_CHARS,
    DiscoveredMcpPrompt,
    DiscoveredMcpResource,
    RejectedMcpMirrorEntry,
    _prompt_argument_metadata,
    metadata_credential_finding,
    normalize_mcp_resource_text,
    prompt_identifier_error,
)
from .mcp_resource_credentials import mcp_resource_uri_credential_finding
from .mcp_resource_identity import (
    governed_mcp_resource_uri,
    mcp_prompt_binding_key,
    mcp_resource_binding_key,
    mcp_resource_identity_digest,
)


def _resource_entry(
    server_name: str,
    resource: Any,
    seen: set[str],
) -> DiscoveredMcpResource | RejectedMcpMirrorEntry | None:
    """Classify one client resource object: mirrorable, rejected, or skipped (``None``)."""
    raw_uri = getattr(resource, "uri", "")
    credential_finding = mcp_resource_uri_credential_finding(raw_uri)
    if credential_finding:
        # Never mirrored, so never addressable and never read. A
        # credential-bearing URI is also not the URI any approved binding was
        # keyed by, so it carries no catalog key.
        return RejectedMcpMirrorEntry(reason=credential_finding)
    governed_uri = governed_mcp_resource_uri(raw_uri)
    if not governed_uri:
        return None
    addressable = len(governed_uri) <= MAX_MCP_RESOURCE_URI_CHARS
    identity = mcp_resource_identity_digest(server_name, governed_uri) if addressable else ""
    metadata_finding = metadata_credential_finding(
        [
            ("name", getattr(resource, "name", "")),
            ("description", getattr(resource, "description", "")),
            ("mimeType", getattr(resource, "mime_type", "") or ""),
        ]
    )
    if metadata_finding:
        # Provider-controlled metadata carries a credential. The item is not
        # mirrored at all, so it can never be listed, approved, or read — but
        # its identity is unchanged, so an already-approved binding for it is
        # preserved rather than retired as if the server had dropped it.
        return RejectedMcpMirrorEntry(
            reason=metadata_finding,
            binding_key=mcp_resource_binding_key(server_name, identity) if identity else "",
        )
    if not addressable:
        return RejectedMcpMirrorEntry(reason="uri_too_long")
    if identity in seen:
        # Two raw URIs that redact to the same governed URI collapse onto one
        # binding; the first one is mirrored and owns the key.
        return RejectedMcpMirrorEntry(reason="duplicate_governed_uri")
    seen.add(identity)
    return DiscoveredMcpResource(
        governed_uri=governed_uri,
        identity=identity,
        name=normalize_mcp_resource_text(getattr(resource, "name", ""), max_chars=_MAX_NAME_CHARS),
        description=normalize_mcp_resource_text(getattr(resource, "description", "")),
        mime_type=normalize_mcp_resource_text(
            getattr(resource, "mime_type", "") or "", max_chars=_MAX_MIME_TYPE_CHARS
        ),
    )


def discovered_mcp_resources(
    server_name: str,
    resources: Sequence[Any],
) -> tuple[list[DiscoveredMcpResource], list[RejectedMcpMirrorEntry]]:
    """Split MCP client resource objects into mirrorable resources and rejections.

    Credential inspection — the URI first, then every provider-controlled
    metadata field — runs before any identifier diagnostic, and a rejection is
    reported by its closed reason code alone. Neither the raw URI nor the
    governed one is ever echoed: a governed URI still names an internal host, a
    bucket, or a database.
    """
    discovered: list[DiscoveredMcpResource] = []
    rejected: list[RejectedMcpMirrorEntry] = []
    seen: set[str] = set()
    for resource in resources or []:
        entry = _resource_entry(server_name, resource, seen)
        if isinstance(entry, RejectedMcpMirrorEntry):
            rejected.append(entry)
        elif entry is not None:
            discovered.append(entry)
    return discovered, rejected


def normalize_mcp_prompt_arguments(arguments: Any) -> tuple[dict[str, Any], ...]:
    """Return the deterministic public argument contract of one prompt."""
    if not isinstance(arguments, (list, tuple)):
        return ()
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for argument in arguments[:_MAX_PROMPT_ARGUMENTS]:
        argument = argument if isinstance(argument, dict) else {}
        name = str(argument.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        entry: dict[str, Any] = {"name": name, "required": bool(argument.get("required"))}
        description = normalize_mcp_resource_text(argument.get("description"))
        if description:
            entry["description"] = description
        normalized.append(entry)
    return tuple(sorted(normalized, key=lambda item: item["name"]))


def discovered_mcp_prompts(
    server_name: str,
    prompts: Sequence[Any],
) -> tuple[list[DiscoveredMcpPrompt], list[RejectedMcpMirrorEntry]]:
    """Split MCP client prompt objects into mirrorable prompts and rejections.

    A prompt name is the most hostile field on this surface: it is
    provider-controlled, unbounded, and used as an identifier. So the credential
    rule is applied to it *before* it is judged as an identifier, and a rejected
    name is never echoed — an oversized or ambiguous name is reported as its
    closed diagnostic code, which is bounded by construction.
    """
    discovered: list[DiscoveredMcpPrompt] = []
    rejected: list[RejectedMcpMirrorEntry] = []
    seen: set[str] = set()
    for prompt in prompts or []:
        raw_name = getattr(prompt, "name", "")
        metadata_finding = metadata_credential_finding(
            [
                ("name", raw_name),
                ("description", getattr(prompt, "description", "")),
                *_prompt_argument_metadata(getattr(prompt, "arguments", None)),
            ]
        )
        name = str(raw_name or "").strip()
        error = prompt_identifier_error(server_name, name)
        if metadata_finding:
            rejected.append(
                RejectedMcpMirrorEntry(
                    reason=metadata_finding,
                    # A credential in a description leaves the prompt's identity
                    # intact, so an approved binding for it is preserved. An
                    # unaddressable name has no binding to preserve.
                    binding_key=mcp_prompt_binding_key(server_name, name) if error is None else "",
                )
            )
            continue
        if error == "empty_prompt_name":
            continue
        if error is not None:
            rejected.append(RejectedMcpMirrorEntry(reason=error))
            continue
        if name in seen:
            continue
        seen.add(name)
        discovered.append(
            DiscoveredMcpPrompt(
                name=name,
                description=normalize_mcp_resource_text(getattr(prompt, "description", "")),
                arguments=normalize_mcp_prompt_arguments(getattr(prompt, "arguments", None)),
            )
        )
    return discovered, rejected


__all__ = [
    "discovered_mcp_prompts",
    "discovered_mcp_resources",
    "normalize_mcp_prompt_arguments",
]
