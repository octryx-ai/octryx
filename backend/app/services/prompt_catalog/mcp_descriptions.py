"""Knowledge MCP tool descriptions resolved per request from the prompt catalog."""

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
    def __init__(
        self,
        *args: Any,
        prompt_set_for_request: PromptSetForRequest,
        hidden_tools_for_request: HiddenToolsForRequest | None = None,
        tool_call_guard: Any = None,
        session_surface: Any = None,
        bind_request: Callable[[FastMCP], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._prompt_set_for_request = prompt_set_for_request
        self._hidden_tools_for_request = hidden_tools_for_request
        # The registry tools and the session view over these tools (``mcp_session_surface.SessionSurface``).
        self._session_surface = session_surface
        # Binds the request's acting person before any tool is listed or called (a server runner's turn owner).
        self._bind_request = bind_request
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
        return {tool.name: tool.description or "" for tool in self._tool_manager.list_tools()}

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._bind_request is not None:
            await self._bind_request(self)
        if self._tool_call_guard is None:
            return await self._dispatch(name, arguments)
        return await self._tool_call_guard(self, name, arguments, self._dispatch)

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session_surface is None:
            return await super().call_tool(name, arguments)
        return await self._session_surface.call(self, name, arguments, super().call_tool, self._own_tools)

    async def _own_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        if self._hidden_tools_for_request is not None:
            hidden = await self._hidden_tools_for_request(self, [tool.name for tool in tools])
            tools = [tool for tool in tools if tool.name not in hidden]
        return tools

    async def visible_tools(self) -> list[MCPTool]:
        # Every tool this request's connection may see, before the session view lists the basic set.
        tools = await self._own_tools()
        if self._session_surface is not None:
            tools = await self._session_surface.visible_tools(self, tools)
        return tools

    def own_tool_names(self) -> frozenset[str]:
        return frozenset(tool.name for tool in self._tool_manager.list_tools())

    async def list_tools(self) -> list[MCPTool]:
        if self._bind_request is not None:
            await self._bind_request(self)
        tools = await self._own_tools()
        if self._session_surface is not None:
            tools = await self._session_surface.list_tools(self, tools)
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
