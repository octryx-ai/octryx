"""Registers the workflow and work-status tools, resources and prompts on the Knowledge MCP server.

Everything runs through ``mcp_parity_dispatch.run_parity_mcp_tool``: the scope, the rate limit, the
connection's Workspace and the audit. A Claude Code user never picks a mode. They ask, and Claude Code
reads the workflow catalog (tool or resource) and selects the definition that fits. It then follows
the returned contract, and asks the user through the confirmation when the definition's
``capability_class`` is above ``read_only``.

Resource: ``octryx://workflow-catalog``: the published definitions.
"""

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
            "List the Workspace's published workflows with their capability_class. Each runs as a workflow run "
            "for a Work item that starts once the user confirms it. Pick one whose when_to_use fits the request "
            "and call workflow_select with the Work item." + _WORKSPACE_NOTE
        )
    )
    async def workflow_catalog(ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "workflow_catalog", {})

    @server.tool(
        description=(
            "Follow a Work item's workflow run: with work_item (or run_id) the session follows that run and the "
            "answer is the run contract (workflow_run). A published workflow (workflow_key) without a run starts "
            "once the user confirms it: the answer is needs_confirmation with an approval_id; ask the user to "
            "confirm via workflow_confirm (or in Octryx). "
            "runtime (server | terminal | device) says where a started run executes; empty: where this session "
            "runs (this device's folder, or this terminal)."
            + _WORKSPACE_NOTE
        )
    )
    async def workflow_select(
        workflow_key: str = "", work_item: str | None = None, run_id: str | None = None,
        repository: str | None = None, runtime: str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        # A Work item or run binds this session to its workflow run (contract v2 in the answer).
        return await call(ctx, "workflow_select", {"workflow_key": workflow_key, "work_item": work_item,
                                                   "run_id": run_id, "repository": repository, "runtime": runtime})

    @server.tool(
        description=(
            "The workflow run this session follows: its current phase (capability_class, tools, path rules, the "
            "confirmed tests it protects, checks, findings), loop i of n, what it waits for and where the person "
            "decides, and what the next gate needs. The launcher puts this view into your context when it changes; "
            "detail=true adds the code style, the earlier change and the agent's instructions. Only the server "
            "advances a run." + _WORKSPACE_NOTE
        )
    )
    async def workflow_run_status(run_id: str | None = None, detail: bool = False,
                                  ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "workflow_run_status", {"run_id": run_id, "detail": detail})

    @server.tool(
        description=(
            "Ask the platform to act for this session's workflow run: action is one of jira.create_issue, "
            "jira.comment, jira.transition (params.work_state, never a Jira status), scm.create_branch, scm.push, "
            "scm.open_pr, ci.status. It runs on the server with the Workspace's connections (no credentials here), "
            "only within the current phase's class; repeating the same request in the same phase returns the "
            "recorded outcome." + _WORKSPACE_NOTE
        )
    )
    async def workflow_action_request(
        action: str, params: dict[str, Any] | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "workflow_action_request", {"action": action, "params": params or {}})

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

    @server.tool(
        description=(
            "Take the user's decision of what this session's workflow run waits for, when the run contract's "
            "decision says in_terminal: a user confirmation (action confirm, change or stop), a user question "
            "(action reply with reply text) or a paused run (continue with k, retry_action, change_plan, abort). "
            "Stop and abort carry the user's reason. Pass the "
            "decision's payload_hash. Only call it after the user told you their decision; they confirm it again "
            "in the permission prompt, which shows the exact payload. Approvals by another person and watched "
            "external states are decided in Octryx, never here." + _WORKSPACE_NOTE
        )
    )
    async def workflow_decide(
        run_id: str, action: str, payload_hash: str, k: int | None = None, reply: str | None = None,
        human_verified_criteria: list[str] | None = None, confirmation_ticket: str | None = None,
        reason: str | None = None, ctx: Context | None = None,
    ) -> dict[str, Any]:
        # The ticket is added by the launcher's hook after the user's permission prompt; never by the model.
        return await call(ctx, "workflow_decide", {
            "run_id": run_id, "action": action, "payload_hash": payload_hash, "k": k, "reply": reply,
            "human_verified_criteria": human_verified_criteria, "confirmation_ticket": confirmation_ticket,
            "reason": reason})

    from .mcp_phase_output_registration import register_phase_output_tools

    register_phase_output_tools(server, call, workspace_note=_WORKSPACE_NOTE)

    @server.tool(description="Read one approval you may see (status, action, session or run)." + _WORKSPACE_NOTE)
    async def approval_get(approval_id: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "approval_get", {"approval_id": approval_id})

    @server.tool(description="List the newest workflow runs and scheduled task runs you may read." + _WORKSPACE_NOTE)
    async def product_run_list(ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "product_run_list", {})

    @server.resource(
        "octryx://workflow-catalog",
        name="workflow-catalog",
        description="The Workspace's published workflows.",
        mime_type="application/json",
    )
    async def workflow_catalog_resource(ctx: Context) -> str:
        return json.dumps(await call(ctx, "workflow_catalog", {}), ensure_ascii=False)


__all__ = ["register_parity_tools"]
