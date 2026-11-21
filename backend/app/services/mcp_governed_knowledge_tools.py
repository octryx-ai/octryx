"""Registers the governed Knowledge and Memory tools on the Knowledge MCP server.

The schemas mirror the chat tool definitions (``tools/definitions/knowledge_evidence.py`` and
``knowledge_memory.py``) and, like them, have no ``project_id``: the Workspace comes from the OAuth
grant or the connection header (``services/mcp_governed_knowledge``). The only renamed argument is
``memory_class`` for the chat's ``class``, which is a Python keyword.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..db import async_session_factory
from .mcp_auto_session import mcp_client_name
from .mcp_governed_knowledge import SESSION_HEADER, WORKSPACE_HEADER, McpCaller, run_governed_mcp_tool

AuthenticatedContext = Callable[[Context | None], tuple[str, list[str] | None, str | None, tuple[str, ...]]]

CLIENT_TOOL_USE_ID_META = "claudecode/toolUseId"
_WORKSPACE_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."


def mcp_caller(ctx: Context | None, authenticate: AuthenticatedContext) -> McpCaller:
    user_id, bound_project_ids, grant_id, scopes = authenticate(ctx)
    request = getattr(ctx.request_context, "request", None) if ctx is not None else None
    headers = getattr(request, "headers", None)
    header = headers.get(WORKSPACE_HEADER) if headers is not None else None
    session_key = headers.get(SESSION_HEADER) if headers is not None else None
    try:
        request_ref = str(ctx.request_id) if ctx is not None else None
    except (AttributeError, ValueError):
        request_ref = None
    tool_use_id = _client_tool_use_id(ctx)
    return McpCaller(
        user_id=user_id,
        grant_id=grant_id,
        scopes=scopes,
        bound_project_ids=tuple(bound_project_ids or ()),
        workspace_header=header,
        client_name=mcp_client_name(ctx),
        request_ref=request_ref,
        session_key=session_key,
        tool_use_id=tool_use_id,
    )


def _client_tool_use_id(ctx: Context | None) -> str | None:
    """Claude Code's ``_meta["claudecode/toolUseId"]`` of this call; ``None`` when absent or malformed."""
    try:
        meta = ctx.request_context.meta if ctx is not None else None
    except (AttributeError, ValueError):
        return None
    extra = getattr(meta, "model_extra", None) or {}
    value = extra.get(CLIENT_TOOL_USE_ID_META)
    return value if isinstance(value, str) and 0 < len(value) <= 64 and value.isprintable() else None


def register_governed_knowledge_tools(server: FastMCP, authenticate: AuthenticatedContext) -> None:
    async def call(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        # Unset optional arguments stay absent, so the tool applies its own defaults and bounds.
        present = {key: value for key, value in arguments.items() if value is not None}
        async with async_session_factory() as db:
            result = await run_governed_mcp_tool(db, caller=caller, tool_name=tool_name, arguments=present)
            await db.commit()
            return result

    @server.tool(
        description=(
            "Read a knowledge_search passage with its neighbouring paragraphs (window 0-3). Read-only."
            + _WORKSPACE_NOTE
        )
    )
    async def knowledge_read(
        evidence_key: str, window: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "knowledge_read", {"evidence_key": evidence_key, "window": window})

    @server.tool(
        description=(
            "List cited changes of one product between two versions (e.g. spring-boot 3.5 to 4.0). Read-only."
            + _WORKSPACE_NOTE
        )
    )
    async def knowledge_changes(
        product: str,
        to_version: str,
        from_version: str | None = None,
        query: str | None = None,
        limit: int | None = None,
        changes_only: bool | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "knowledge_changes",
            {
                "product": product,
                "to_version": to_version,
                "from_version": from_version,
                "query": query,
                "limit": limit,
                "changes_only": changes_only,
            },
        )

    @server.tool(
        description=(
            "Where a product version change (e.g. spring-boot 3.5 to 4.0) applies in THIS codebase: every "
            "cited change fact with the exact file:line and an openable link per location. The codebase is "
            "the session's checkout bound by octryx-claude, or pass files=[{path, content}] (build files, "
            "application config, sources) to ask about files you have locally; repository picks one of "
            "the candidates when asked. Read-only." + _WORKSPACE_NOTE
        )
    )
    async def knowledge_code_impact(
        product: str,
        to_version: str,
        from_version: str | None = None,
        files: list[dict[str, str]] | None = None,
        commit: str | None = None,
        repository: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "knowledge_code_impact",
            {
                "product": product,
                "to_version": to_version,
                "from_version": from_version,
                "files": files,
                "commit": commit,
                "repository": repository,
            },
        )

    @server.tool(
        description=(
            "Recall memories from earlier sessions (the user's personal preferences, the team's decisions, "
            "conventions and learnings). Memory is NOT source evidence: never cite it as a source; present it "
            "with its present_as wording, and prefer Knowledge evidence when they disagree. Read-only."
            + _WORKSPACE_NOTE
        )
    )
    async def memory_recall(
        query: str | None = None,
        classes: list[str] | None = None,
        limit: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(ctx, "memory_recall", {"query": query, "classes": classes, "limit": limit})

    @server.tool(
        description=(
            "Remember something the user explicitly asked to be remembered, in their own words. Personal by "
            "default; scope 'workspace' (team memory) needs the Workspace admin or owner role. Never for "
            "credentials or secrets (refused). Needs the knowledge:write scope." + _WORKSPACE_NOTE
        )
    )
    async def memory_remember(
        text: str,
        scope: str | None = None,
        memory_class: str | None = None,
        product: str | None = None,
        expires_in_days: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "memory_remember",
            {
                "text": text,
                "scope": scope,
                "class": memory_class,
                "product": product,
                "expires_in_days": expires_in_days,
            },
        )


__all__ = ["AuthenticatedContext", "mcp_caller", "register_governed_knowledge_tools"]
