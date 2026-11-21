"""Knowledge MCP tool descriptions resolved per request from the prompt catalog.

The Knowledge MCP server registers its tools with code descriptions at construction. Those
descriptions are catalog keys ``mcp.<tool>.description`` (literal, high risk), seeded by the
registration itself (``mcp_description_specs`` builds the server once to read them).

``CatalogFastMCP.list_tools`` resolves the descriptions on every ``tools/list`` request, at
the scope of the connection's Workspace (the grant binding or the Workspace header, when the
caller may read it; otherwise global):

1. a catalog version of ``mcp.<tool>.description`` is served verbatim;
2. otherwise a description composed from a chat tool's code description (for example
   ``knowledge_search``: the chat description plus the connection note) gets the served chat
   description (``tool.<tool>.description`` and the citation rule) in place of that part;
3. otherwise the code description is served.

So MCP clients see an admin edit on their next ``tools/list``; nothing is cached per server.

The server ``instructions`` (sent once, in the ``initialize`` answer) are resolved per request
too: the token verifier binds the connection's served text (``bind_connection_instructions``)
before the request is handled, and the initialization options carry it. The token alone names
the scope, so instructions resolve at the grant's single bound Workspace, else globally (the
Workspace header is read later, by the tools).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool

from .contract import RISK_HIGH, PromptKeySpec
from .prompt_set import PromptSet
from .registry import prompt_key_registry
from .tool_catalog import tool_description_key
from .tool_descriptions import catalog_override, resolved_tool_description

MCP_AREA = "mcp"

#: Resolves the connection's prompt set for the current request (Workspace scope or global).
PromptSetForRequest = Callable[[FastMCP], Awaitable[PromptSet]]
# The tool names the connection may not see (``tools/list``); the call path refuses them on its own.
HiddenToolsForRequest = Callable[[FastMCP, list[str]], Awaitable[frozenset[str]]]

_CONNECTION_INSTRUCTIONS: ContextVar[str | None] = ContextVar("mcp_connection_instructions", default=None)


def bind_connection_instructions(text: str | None) -> None:
    """The served instructions of the current request's connection (set during token verification)."""
    _CONNECTION_INSTRUCTIONS.set(text)


def mcp_description_key(tool_name: str) -> str:
    return f"mcp.{tool_name}.description"


def served_mcp_description(prompt_set: PromptSet, tool_name: str, code_description: str) -> str:
    edited = catalog_override(prompt_set, mcp_description_key(tool_name))
    if edited is not None:
        return edited
    chat = prompt_key_registry().get(tool_description_key(tool_name))
    if chat is not None and code_description.startswith(chat.seed):
        suffix = code_description[len(chat.seed) :]
        return resolved_tool_description(prompt_set, tool_name, chat.seed) + suffix
    return code_description


def catalog_mcp_tools(prompt_set: PromptSet, tools: list[MCPTool]) -> list[MCPTool]:
    served = []
    for tool in tools:
        code = tool.description or ""
        description = served_mcp_description(prompt_set, tool.name, code) if code else code
        served.append(tool if description == code else tool.model_copy(update={"description": description}))
    return served


class CatalogFastMCP(FastMCP):
    """A FastMCP server whose ``tools/list`` serves the catalog's tool descriptions."""

    def __init__(
        self,
        *args: Any,
        prompt_set_for_request: PromptSetForRequest,
        hidden_tools_for_request: HiddenToolsForRequest | None = None,
        tool_call_guard: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._prompt_set_for_request = prompt_set_for_request
        self._hidden_tools_for_request = hidden_tools_for_request
        # ``guard(server, name, arguments, call)`` around every tools/call (``mcp_seat_analysis_guard``).
        self._tool_call_guard = tool_call_guard
        low_level = self._mcp_server
        code_options = low_level.create_initialization_options

        def initialization_options(*options_args: Any, **options_kwargs: Any) -> Any:
            options = code_options(*options_args, **options_kwargs)
            served = _CONNECTION_INSTRUCTIONS.get()
            return options if served is None else options.model_copy(update={"instructions": served})

        low_level.create_initialization_options = initialization_options

    def code_tool_descriptions(self) -> dict[str, str]:
        """The descriptions as registered in code (the seeds of the ``mcp.*`` keys)."""
        return {tool.name: tool.description or "" for tool in self._tool_manager.list_tools()}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._tool_call_guard is None:
            return await super().call_tool(name, arguments)
        return await self._tool_call_guard(self, name, arguments, super().call_tool)

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        if self._hidden_tools_for_request is not None:
            hidden = await self._hidden_tools_for_request(self, [tool.name for tool in tools])
            tools = [tool for tool in tools if tool.name not in hidden]
        return catalog_mcp_tools(await self._prompt_set_for_request(self), tools)


def mcp_description_specs() -> tuple[PromptKeySpec, ...]:
    from ..mcp_knowledge_protocol import build_knowledge_mcp_server

    server = build_knowledge_mcp_server()
    return tuple(
        PromptKeySpec(
            key=mcp_description_key(name),
            area=MCP_AREA,
            title=f"{name}: Knowledge MCP description",
            seed=description,
            risk=RISK_HIGH,
            description="Description of the Knowledge MCP tool as MCP clients see it in tools/list.",
            literal=True,
        )
        for name, description in sorted(server.code_tool_descriptions().items())
        if description
    )


__all__ = [
    "MCP_AREA",
    "CatalogFastMCP",
    "bind_connection_instructions",
    "catalog_mcp_tools",
    "mcp_description_key",
    "mcp_description_specs",
    "served_mcp_description",
]
