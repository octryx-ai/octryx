"""Typed resource and prompt discovery for one MCP server."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.services.error_facts import error_text

from .models import MCPPrompt, MCPResource

log = logging.getLogger(__name__)

DISCOVERY_OK = "ok"
DISCOVERY_UNSUPPORTED = "unsupported"
DISCOVERY_NOT_CONNECTED = "not_connected"
DISCOVERY_FAILED = "discovery_failed"
MCP_DISCOVERY_STATES = (DISCOVERY_OK, DISCOVERY_UNSUPPORTED, DISCOVERY_NOT_CONNECTED, DISCOVERY_FAILED)

# JSON-RPC "method not found": the server does not implement this capability.
_METHOD_NOT_FOUND = -32601

RESOURCE_KIND = "resources"
PROMPT_KIND = "prompts"


@dataclass(frozen=True, slots=True)
class McpCatalogListing:
    kind: str
    state: str
    items: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def succeeded(self) -> bool:
        return self.state in (DISCOVERY_OK, DISCOVERY_UNSUPPORTED)


def _is_unsupported(error: BaseException) -> bool:
    code = getattr(getattr(error, "error", None), "code", None)
    return code == _METHOD_NOT_FOUND


async def _discover(
    manager: Any,
    server_name: str,
    *,
    kind: str,
    call: Callable[[Any], Any],
    build: Callable[[Any, str], list[Any]],
) -> McpCatalogListing:
    session = manager.get_session(server_name) if hasattr(manager, "get_session") else None
    if session is None:
        return McpCatalogListing(kind=kind, state=DISCOVERY_NOT_CONNECTED)
    try:
        response = await call(session)
    except Exception as error:
        if _is_unsupported(error):
            return McpCatalogListing(kind=kind, state=DISCOVERY_UNSUPPORTED)
        log.error(
            "Failed to list %s from '%s': %s",
            kind,
            server_name,
            error_text("mcp_catalog_list_failed", error),
        )
        return McpCatalogListing(kind=kind, state=DISCOVERY_FAILED)
    return McpCatalogListing(kind=kind, state=DISCOVERY_OK, items=tuple(build(response, server_name)))


def _resources(response: Any, server_name: str) -> list[MCPResource]:
    return [
        MCPResource(
            uri=resource.uri,
            name=resource.name or "",
            description=resource.description or "",
            mime_type=resource.mimeType if hasattr(resource, "mimeType") else None,
            server_name=server_name,
            server_id=server_name,
        )
        for resource in getattr(response, "resources", None) or []
    ]


def _prompts(response: Any, server_name: str) -> list[MCPPrompt]:
    return [
        MCPPrompt(
            name=prompt.name,
            description=prompt.description or "",
            arguments=[
                {
                    "name": argument.name,
                    "description": argument.description or "",
                    # Carried so the mirrored prompt contract can detect a real
                    # argument-contract change.
                    "required": bool(getattr(argument, "required", False)),
                }
                for argument in (prompt.arguments or [])
            ],
            server_name=server_name,
            server_id=server_name,
        )
        for prompt in getattr(response, "prompts", None) or []
    ]


async def discover_mcp_resources(manager: Any, server_name: str) -> McpCatalogListing:
    return await _discover(
        manager,
        server_name,
        kind=RESOURCE_KIND,
        call=lambda session: session.list_resources(),
        build=_resources,
    )


async def discover_mcp_prompts(manager: Any, server_name: str) -> McpCatalogListing:
    return await _discover(
        manager,
        server_name,
        kind=PROMPT_KIND,
        call=lambda session: session.list_prompts(),
        build=_prompts,
    )


def failed_discovery_kinds(listings: Sequence[McpCatalogListing]) -> list[str]:
    return sorted({listing.kind for listing in listings if not listing.succeeded})


__all__ = [
    "DISCOVERY_FAILED",
    "DISCOVERY_NOT_CONNECTED",
    "DISCOVERY_OK",
    "DISCOVERY_UNSUPPORTED",
    "MCP_DISCOVERY_STATES",
    "PROMPT_KIND",
    "RESOURCE_KIND",
    "McpCatalogListing",
    "discover_mcp_prompts",
    "discover_mcp_resources",
    "failed_discovery_kinds",
]
