"""Persisted arguments of governed MCP requests: a resource read keeps the opaque identity, not the address."""

from __future__ import annotations

from typing import Any

from ..redaction_policy import (
    REDACTED_SECRET,
    redact_secret_payload,
    redact_secret_text,
)
from .resource_credentials import mcp_resource_uri_credential_finding
from .resource_identity import (
    MCP_PROMPT_GET_TOOL,
    MCP_PROMPT_LIST_TOOL,
    MCP_RESOURCE_LIST_TOOL,
    MCP_RESOURCE_READ_TOOL,
    normalized_mcp_resource_identity,
)

MCP_RESOURCE_ID_PARAM = "resource_id"

_MAX_SEARCH_CHARS = 200
_MAX_IDENTIFIER_CHARS = 200
_INVALID_RESOURCE_ID = "invalid_resource_id"


def governed_argument_value(value: Any) -> Any:
    # Secrets and credential URIs are removed.
    redacted = redact_secret_payload(value, max_string_length=_MAX_SEARCH_CHARS)
    if isinstance(redacted, str) and mcp_resource_uri_credential_finding(redacted):
        return REDACTED_SECRET
    if isinstance(redacted, dict):
        return {key: governed_argument_value(item) for key, item in redacted.items()}
    if isinstance(redacted, list):
        return [governed_argument_value(item) for item in redacted]
    return redacted


def _bounded_identifier(value: Any) -> str:
    # Bounded and secret-free, safe to persist and echo.
    text = redact_secret_text(value, max_chars=_MAX_IDENTIFIER_CHARS)
    return REDACTED_SECRET if mcp_resource_uri_credential_finding(text) else text


def publishable_mcp_resource_arguments(tool_name: str, arguments: Any) -> dict[str, Any] | None:
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
