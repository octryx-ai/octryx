"""What a governed MCP resource or prompt request may carry outside the boundary.

A bridge-tool call is model-supplied and reaches durable storage — the
``ToolCall`` row, the assistant message, the turn trace, the runtime event
stream — *before* governance has decided anything. Raw arguments can therefore
never be what those writers store: a resource URI can embed userinfo
(``postgres://user:password@host/db``), an object-store presign query
(``?X-Amz-Signature=...&X-Amz-Credential=...``), or a bearer token, and a prompt
argument can hold a credential outright. The shared
``redaction_policy.redact_secret_text`` rewrites URI userinfo (any
scheme) but not a presign query, which would survive it.

Two rules follow: the opaque identity below, and the credential rules in
``mcp_resource_credentials``.

**The addressable identity is opaque.** ``read_mcp_server_resource`` takes the
catalog identity digest that ``list_mcp_server_resources`` published, never a
URI. There is no URI channel into the platform at all, so there is nothing to
redact on the way in and nothing raw to persist: the governed URI lives in the
Workspace catalog and reaches the transport from there.

Credential-bearing URIs and provider fields are recognised by
``mcp_resource_credentials``; a value that carries one is never persisted here.

Everything here is pure: no database, no MCP client, no connection
configuration. ``tools/argument_sanitizers`` is the generic seam that applies it
at the persistence and publish sites.
"""

from __future__ import annotations

from typing import Any

from .mcp_resource_credentials import mcp_resource_uri_credential_finding
from .mcp_resource_identity import (
    MCP_PROMPT_GET_TOOL,
    MCP_PROMPT_LIST_TOOL,
    MCP_RESOURCE_LIST_TOOL,
    MCP_RESOURCE_READ_TOOL,
    normalized_mcp_resource_identity,
)
from .redaction_policy import (
    REDACTED_SECRET,
    redact_secret_payload,
    redact_secret_text,
)

MCP_RESOURCE_ID_PARAM = "resource_id"

_MAX_SEARCH_CHARS = 200
_MAX_IDENTIFIER_CHARS = 200
_INVALID_RESOURCE_ID = "invalid_resource_id"


def governed_argument_value(value: Any) -> Any:
    """Return one persistable argument value: secrets and credential URIs removed."""
    redacted = redact_secret_payload(value, max_string_length=_MAX_SEARCH_CHARS)
    if isinstance(redacted, str) and mcp_resource_uri_credential_finding(redacted):
        return REDACTED_SECRET
    if isinstance(redacted, dict):
        return {key: governed_argument_value(item) for key, item in redacted.items()}
    if isinstance(redacted, list):
        return [governed_argument_value(item) for item in redacted]
    return redacted


def _bounded_identifier(value: Any) -> str:
    """Return a bounded, secret-free identifier safe to persist and echo."""
    text = redact_secret_text(value, max_chars=_MAX_IDENTIFIER_CHARS)
    return REDACTED_SECRET if mcp_resource_uri_credential_finding(text) else text


def publishable_mcp_resource_arguments(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Return the persistable projection of one bridge-tool call, or ``None``.

    ``None`` means this tool is not part of the governed resource surface and its
    arguments are none of this module's business.
    """
    normalized_tool = str(tool_name or "").strip()
    payload = arguments if isinstance(arguments, dict) else {}
    if normalized_tool not in {
        MCP_RESOURCE_LIST_TOOL,
        MCP_RESOURCE_READ_TOOL,
        MCP_PROMPT_LIST_TOOL,
        MCP_PROMPT_GET_TOOL,
    }:
        return None
    governed: dict[str, Any] = {"server_name": _bounded_identifier(payload.get("server_name"))}
    if normalized_tool in {MCP_RESOURCE_LIST_TOOL, MCP_PROMPT_LIST_TOOL}:
        search = redact_secret_text(payload.get("search"), max_chars=_MAX_SEARCH_CHARS)
        if search:
            governed["search"] = search
        return governed
    if normalized_tool == MCP_RESOURCE_READ_TOOL:
        # Only the opaque catalog identity survives. A ``uri`` the model supplied
        # anyway is dropped here and ignored by the gate, so neither the raw form
        # nor a redacted echo of it is ever written.
        identity = normalized_mcp_resource_identity(payload.get(MCP_RESOURCE_ID_PARAM))
        governed[MCP_RESOURCE_ID_PARAM] = identity or _INVALID_RESOURCE_ID
        return governed
    governed["prompt_name"] = _bounded_identifier(payload.get("prompt_name"))
    raw_arguments = payload.get("arguments")
    governed["arguments"] = governed_argument_value(raw_arguments) if isinstance(raw_arguments, dict) else {}
    return governed


__all__ = [
    "MCP_RESOURCE_ID_PARAM",
    "governed_argument_value",
    "publishable_mcp_resource_arguments",
]
