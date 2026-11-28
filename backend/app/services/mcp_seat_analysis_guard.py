"""The native-protocol wiring of the seat analysis gate (``work_item_analysis.seat_mcp_gate``). A pinned analysis
session's call outside its tool set is refused."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from mcp.server.fastmcp import Context
from mcp.types import CallToolResult, TextContent

from ..db import async_session_factory
from .agent_tools_deny import run_session_mcp_refusal
from .mcp_governed_knowledge import SESSION_HEADER
from .work_item_analysis.seat_mcp_gate import analysis_tool_refusal, pinned_analysis, record_server_evidence
from .work_item_analysis.seat_session import READ_TOOLS

logger = logging.getLogger(__name__)

CallTool = Callable[[str, dict[str, Any]], Awaitable[Any]]
ToolCallGuard = Callable[[Any, str, dict[str, Any], CallTool], Awaitable[Any]]
AuthenticatedContext = Callable[[Context | None], tuple[str, Any, Any, Any]]


def connection_session_key(ctx: Context | None) -> str | None:
    try:
        request = getattr(ctx.request_context, "request", None) if ctx is not None else None
    except (LookupError, ValueError):
        return None
    headers = getattr(request, "headers", None)
    value = headers.get(SESSION_HEADER) if headers is not None else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _content_and_structured(result: Any) -> tuple[Sequence[Any], Any, bool]:
    if isinstance(result, CallToolResult):
        return result.content, result.structuredContent, bool(result.isError)
    if isinstance(result, tuple) and len(result) == 2:
        return result[0], result[1], False
    if isinstance(result, dict):
        return [], result, False
    return result if isinstance(result, Sequence) else [], None, False


def result_text(result: Any) -> tuple[str, bool]:
    content, structured, is_error = _content_and_structured(result)
    text = "\n".join(block.text for block in content if isinstance(block, TextContent))
    if structured is None:
        try:
            structured = json.loads(text) if text else None
        except ValueError:
            structured = None
    if not text and isinstance(structured, dict):
        text = json.dumps(structured, ensure_ascii=False, default=str)
    return text, is_error or (isinstance(structured, dict) and "error" in structured)


def _refused(refusal: dict[str, str]) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(refusal))], isError=True)


def seat_analysis_tool_guard(authenticated_context: AuthenticatedContext) -> ToolCallGuard:
    async def guard(server: Any, name: str, arguments: dict[str, Any], call: CallTool) -> Any:
        ctx = server.get_context()
        session_key = connection_session_key(ctx)
        if session_key is None:
            return await call(name, arguments)
        async with async_session_factory() as db:
            pinned = await pinned_analysis(db, session_key)
            # A run-bound session's phase deny (phase ∪ the published agent's tools deny) refuses here.
            run_refusal = await run_session_mcp_refusal(db, session_key, name)
        refusal = analysis_tool_refusal(pinned, name)
        if refusal is not None:
            logger.info("MCP tool refused for a seat analysis session: tool=%s", name)
            return _refused(refusal)
        if run_refusal is not None:
            logger.info("MCP tool refused by the run phase's tools deny: tool=%s", name)
            return _refused(run_refusal)
        result = await call(name, arguments)
        if pinned is not None and name in READ_TOOLS:
            user_id = authenticated_context(ctx)[0]
            text, is_error = result_text(result)
            async with async_session_factory() as db:
                if record_server_evidence(db, pinned, user_id=user_id, tool_name=name, text=text, is_error=is_error):
                    await db.commit()
        return result

    return guard


__all__ = ["ToolCallGuard", "connection_session_key", "result_text", "seat_analysis_tool_guard"]
