"""Registers the workflow and work-status tools, resources and prompts on the Knowledge MCP server. Everything runs
through ``mcp_parity_dispatch.run_parity_mcp_tool``."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..db import async_session_factory
from .mcp_governed_knowledge_tools import AuthenticatedContext, mcp_caller
from .mcp_parity_dispatch import run_parity_mcp_tool

_WORKSPACE_NOTE = " The Workspace is this MCP connection's (grant binding or X-Octryx-Workspace header)."


def register_parity_tools(server: FastMCP, authenticate: AuthenticatedContext) -> None:
    async def call(ctx: Context | None, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        caller = mcp_caller(ctx, authenticate)
        present = {key: value for key, value in arguments.items() if value is not None}
        async with async_session_factory() as db:
            result = await run_parity_mcp_tool(db, caller=caller, tool_name=tool_name, arguments=present)
            await db.commit()
            return result

    @server.tool(
        description=(
            "Confirm a pending workflow approval (approval_id from workflow_select). The user is asked in "
            "the permission prompt; only their acceptance approves it. Returns the selected contract."
            + _WORKSPACE_NOTE
        )
    )
    async def workflow_confirm(
        approval_id: str, confirmation_ticket: str | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        # The ticket is added by the launcher's hook after the user's permission prompt; never by the model.
        return await call(
            ctx, "workflow_confirm", {"approval_id": approval_id, "confirmation_ticket": confirmation_ticket}
        )

    from .mcp_phase_output_registration import register_change_plan_tool, register_phase_output_tools

    register_phase_output_tools(server, call, workspace_note=_WORKSPACE_NOTE)
    register_change_plan_tool(server, call, workspace_note=_WORKSPACE_NOTE)

    @server.resource(
        "octryx://workflow-catalog",
        name="workflow-catalog",
        description="The Workspace's published workflows.",
        mime_type="application/json",
    )
    async def workflow_catalog_resource(ctx: Context) -> str:
        return json.dumps(await call(ctx, "workflow_catalog", {}), ensure_ascii=False)


__all__ = ["register_parity_tools"]
