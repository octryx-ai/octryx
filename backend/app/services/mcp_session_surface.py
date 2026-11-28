"""What the session MCP endpoint lists for any engine: a basic set, ``tool_search`` and ``tool_call``, the tools the
session loaded, a phase's tools. Stateless: every call decides the visible set again, never trusting a listing."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool
from sqlalchemy.orm.attributes import flag_modified

from ..db import async_session_factory
from ..models import User
from .data_access import as_viewer
from .mcp_governed_knowledge import failure, resolve_mcp_workspace
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_knowledge_phase import PHASE_RUN_TOOLS, hidden_in_phase, run_phase_allowed
from .mcp_registry_tools import NOT_OFFERED, PERSON_SCOPED_TOOLS, call_registry_tool, member_workspace, offered_tools

TOOL_SEARCH = "tool_search"
TOOL_CALL = "tool_call"
#: Listed in full on every connection; the hook-confirmed tools must be called by their own name.
BASIC_TOOLS = ("knowledge_search", "knowledge_read", "memory_recall", "workflow_run_status", "workflow_select",
               "workflow_confirm", "workflow_decide", "workflow_action_request")
LOADED_KEY = "mcp_loaded_tools"
SEARCH_LIMIT = 6
SELECT_LIMIT = 20
_MAX_LOADED = 64

HandWrittenCall = Callable[[str, dict[str, Any]], Awaitable[Any]]


def _search_tool(catalog: str) -> MCPTool:
    return MCPTool(name=TOOL_SEARCH, description=(
        "More tools of this session, by family. Search with keywords (e.g. 'confluence page', 'pull requests') or "
        "select:<name>,<name> for names you know; the answer gives each tool's name, description and input schema. "
        "Call a found tool with tool_call. If nothing found does what the person asked, say it is not available and "
        "stop.\n" + catalog),
        inputSchema={"type": "object", "properties": {"query": {
            "type": "string", "description": "keywords, or select:<name>[,<name>...] for exact names"}},
            "required": ["query"]})


_CALL_TOOL = MCPTool(name=TOOL_CALL, description=(
    "Call a tool tool_search found, by its name, with the arguments its input schema names."),
    inputSchema={"type": "object", "properties": {"name": {"type": "string"},
                                                  "arguments": {"type": "object"}}, "required": ["name"]})


def _catalog(tools: list[MCPTool]) -> dict[str, dict[str, Any]]:
    return {tool.name: {"type": "function", "function": {"name": tool.name, "description": tool.description or "",
                                                         "parameters": tool.inputSchema}} for tool in tools}


def _families_line(names: list[str]) -> str:
    from .chat_deferred_tools import compact_catalog
    from .governed_default_tool_sets import governed_default_tool_set

    # The chat's family lines, with the session's own way to write and to start a run.
    return compact_catalog(names, governed_default_tool_set("diagnosis").families,
                           write_note="each call approved in Octryx",
                           hints={"workflow_selection": "list_available_workflows"})


def listed(tools: list[MCPTool], *, loaded: set[str], phase: set[str] | None) -> list[MCPTool]:
    # ``phase``: the narrow set a session runs in (its run phase's tools, a seat analysis set), listed in full.
    keep = {*BASIC_TOOLS, *loaded, *(phase or ()), *(PHASE_RUN_TOOLS if phase else ())}
    shown = [tool for tool in tools if tool.name in keep]
    deferred = [tool.name for tool in tools if tool.name not in keep]
    return [*shown, _search_tool(_families_line(deferred)), _CALL_TOOL] if deferred else shown


def search(tools: list[MCPTool], query: str, shown: set[str]) -> dict[str, Any]:
    from .chat_deferred_tools import select_tool_names

    catalog = _catalog(tools)
    limit = SELECT_LIMIT if query.strip().lower().startswith("select:") else SEARCH_LIMIT
    names = [name for name in select_tool_names(query, catalog, core=shown) if name in catalog][:limit]
    if not names:
        return {"tools": [], "note": "No offered tool is close. If the person asked for it, tell them it is not "
                                     "available here and stop; do not use a different tool instead."}
    return {"tools": [{"name": name, "description": catalog[name]["function"]["description"],
                       "input_schema": catalog[name]["function"]["parameters"]} for name in names],
            "note": "Call one with tool_call (name and arguments)."}


def _result(payload: dict[str, Any]) -> CallToolResult:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    # A typed state (denied, not_found, needs_configuration) is an answer, as from the hand-written tools; an
    # untyped error or a call waiting for approval is a failed call.
    return CallToolResult(content=[TextContent(type="text", text=text)], structuredContent=json.loads(text),
                          isError="error" in payload and "state" not in payload)


class SessionSurface:

    def __init__(self, authenticate: AuthenticatedContext, hand_written: Callable[[FastMCP], frozenset[str]],
                 session_factory: Callable[[], Any] = async_session_factory):
        self._authenticate = authenticate
        self._hand_written = hand_written
        self._session_factory = session_factory

    def _caller(self, server: FastMCP) -> Any:
        try:
            return mcp_caller(server.get_context(), self._authenticate)
        except (HTTPException, ValueError):
            return None

    async def _visible(self, server: FastMCP, db: Any, caller: Any, workspace: str,
                       hand_written: list[MCPTool]) -> tuple[list[MCPTool], set[str] | None]:
        # ``workspace`` empty: the connection names none, and only person-scoped registry tools are offered.
        registry = await offered_tools(db, caller, workspace, self._hand_written(server))
        tools = [*hand_written, *registry]
        phase = await run_phase_allowed(server, db, workspace, self._authenticate) if workspace else None
        if phase:
            hidden = hidden_in_phase([tool.name for tool in registry], phase)
            tools = [tool for tool in tools if tool.name not in hidden]
        pinned = await _analysis_tools(db, caller)
        if pinned is not None:
            # A seat analysis session runs only its analysis set: listed in full, with no search to reach.
            return [tool for tool in tools if tool.name in pinned], set(pinned)
        return tools, phase

    def _scope(self, server: FastMCP) -> tuple[Any, str | dict[str, str] | None]:
        caller = self._caller(server)
        if caller is None:
            return None, None
        workspace = resolve_mcp_workspace(caller)
        # No Workspace named: the person-scoped tools still run. One outside the grant is refused.
        unnamed = isinstance(workspace, dict) and workspace.get("state") == "needs_configuration"
        return caller, "" if unnamed else workspace

    async def visible_tools(self, server: FastMCP, hand_written: list[MCPTool]) -> list[MCPTool]:
        caller, workspace = self._scope(server)
        if caller is None or not isinstance(workspace, str):
            return hand_written
        with as_viewer(caller.user_id):
            async with self._session_factory() as db:
                return (await self._visible(server, db, caller, workspace, hand_written))[0]

    async def list_tools(self, server: FastMCP, hand_written: list[MCPTool]) -> list[MCPTool]:
        caller, workspace = self._scope(server)
        if caller is None or not isinstance(workspace, str):
            return listed(hand_written, loaded=set(), phase=None)
        with as_viewer(caller.user_id):
            async with self._session_factory() as db:
                tools, phase = await self._visible(server, db, caller, workspace, hand_written)
                loaded = set(await _loaded(db, caller, workspace)) if workspace else set()
        return listed(tools, loaded=loaded, phase=phase)

    async def call(self, server: FastMCP, name: str, arguments: dict[str, Any], hand_written_call: HandWrittenCall,
                   hand_written: Callable[[], Awaitable[list[MCPTool]]]) -> Any:
        if name in self._hand_written(server):
            return await hand_written_call(name, arguments)
        caller, workspace = self._scope(server)
        if caller is None:
            return _result(dict(NOT_OFFERED))
        if not isinstance(workspace, str):
            return _result(workspace)
        if not workspace and name not in {TOOL_SEARCH, TOOL_CALL, *PERSON_SCOPED_TOOLS}:
            return _result(failure("needs_configuration"))
        if name in {TOOL_SEARCH, TOOL_CALL}:
            return await self._meta_call(server, caller, workspace, name, arguments, await hand_written())
        with as_viewer(caller.user_id):
            async with self._session_factory() as db:
                result = await call_registry_tool(db, caller=caller, tool_name=name, arguments=arguments,
                                                  skip=self._hand_written(server))
                await db.commit()
        return _result(result)

    async def _meta_call(self, server: FastMCP, caller: Any, workspace: str, name: str, arguments: dict[str, Any],
                         hand_written: list[MCPTool]) -> Any:
        with as_viewer(caller.user_id):
            async with self._session_factory() as db:
                if not await member_workspace(db, caller.user_id, workspace):
                    return _result(failure("not_found"))
                tools, phase = await self._visible(server, db, caller, workspace, hand_written)
                if name == TOOL_SEARCH:
                    shown = {tool.name for tool in listed(tools, loaded=set(), phase=phase)}
                    found = search(tools, str(arguments.get("query") or ""), shown)
                    if workspace:
                        await _remember(db, caller, workspace, [tool["name"] for tool in found["tools"]])
                        await db.commit()
                    return _result(found)
        target = str(arguments.get("name") or "").strip()
        inner = arguments.get("arguments")
        if target in {TOOL_SEARCH, TOOL_CALL} or target not in {tool.name for tool in tools}:
            return _result(dict(NOT_OFFERED))
        if inner is not None and not isinstance(inner, dict):
            return _result({"state": "denied", "reason": "invalid_arguments",
                            "message": "arguments must be an object of the tool's parameters."})
        return await server.call_tool(target, dict(inner or {}))


async def _analysis_tools(db: Any, caller: Any) -> frozenset[str] | None:
    from .work_item_analysis.seat_mcp_gate import pinned_analysis
    from .work_item_analysis.seat_session import SESSION_TOOLS

    return frozenset(SESSION_TOOLS) if await pinned_analysis(db, caller.session_key) is not None else None


async def _gateway_session(db: Any, caller: Any, workspace: str) -> Any:
    from .mcp_workflow_run_session import _gateway

    user = await db.get(User, caller.user_id)
    return await _gateway(db, caller, user, workspace) if user is not None and user.is_active else None


async def _loaded(db: Any, caller: Any, workspace: str) -> list[str]:
    session = await _gateway_session(db, caller, workspace)
    metadata = session.metadata_ if session is not None and isinstance(session.metadata_, dict) else {}
    return [str(name) for name in metadata.get(LOADED_KEY) or []]


async def _remember(db: Any, caller: Any, workspace: str, names: list[str]) -> None:
    session = await _gateway_session(db, caller, workspace)
    if session is None or not names:
        return
    metadata = dict(session.metadata_ or {})
    metadata[LOADED_KEY] = list(dict.fromkeys([*(metadata.get(LOADED_KEY) or []), *names]))[-_MAX_LOADED:]
    session.metadata_ = metadata
    flag_modified(session, "metadata_")


__all__ = ["BASIC_TOOLS", "LOADED_KEY", "TOOL_CALL", "TOOL_SEARCH", "SessionSurface", "listed", "search"]
