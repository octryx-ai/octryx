"""The Knowledge MCP server's own tools: projects, tasks, approvals, policy, session ingest.

The call paths come from the protocol module (``mcp_knowledge_protocol``), which checks scopes and audits each call.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context


def register_core_tools(server: Any, *, call_knowledge: Any, call_platform: Any, call_external_session: Any) -> None:
    """Register the core tools in their ``tools/list`` order: platform reads first, then the external session."""
    _register_platform_reads(server, call_knowledge=call_knowledge, call_platform=call_platform)
    _register_external_session_tools(server, call_external_session=call_external_session)


def _register_platform_reads(server: Any, *, call_knowledge: Any, call_platform: Any) -> None:
    @server.tool(
        description="List the projects this grant can access (id + name), for choosing the ingest target."
    )
    async def knowledge_projects(ctx: Context | None = None) -> dict[str, Any]:
        return await call_knowledge(ctx, "knowledge_projects", {})

    @server.tool(description="List the caller's tasks (optionally filtered by project).")
    async def task_list(
        project_id: str | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call_platform(ctx, "task_list", {"project_id": project_id or ""})

    @server.tool(description="List recent runs of one of the caller's tasks.")
    async def task_runs(task_id: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call_platform(ctx, "task_runs", {"task_id": task_id})

    @server.tool(description="List the caller's approval requests by status.")
    async def approval_list(status: str = "pending", ctx: Context | None = None) -> dict[str, Any]:
        return await call_platform(ctx, "approval_list", {"status": status})

    @server.tool(description="Read the effective execution/tool policy for a project.")
    async def policy_effective(project_id: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call_platform(ctx, "policy_effective", {"project_id": project_id})


def _register_external_session_tools(server: Any, *, call_external_session: Any) -> None:
    @server.tool(
        description=(
            "Ingest an external agent session: summary plus per-model token usage. "
            "Usage records: {model, input_tokens (uncached), output_tokens, "
            "cache_read_tokens, cache_creation_tokens, cost_usd?}."
        )
    )
    async def session_ingest(
        project_id: str,
        summary: str = "",
        usage: list[dict[str, Any]] | None = None,
        workspace_ref: str = "",
        client_session_id: str = "",
        transcript_digest: str = "",
        client: str = "",
        work_item_key: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call_external_session(
            ctx,
            "session_ingest",
            {
                "project_id": project_id,
                "summary": summary,
                "usage": usage or [],
                "workspace_ref": workspace_ref,
                "client_session_id": client_session_id,
                "transcript_digest": transcript_digest,
                "client": client,
                "work_item_key": work_item_key,
            },
        )

    @server.tool(description="Request a human approval for a sensitive action (resolved in the platform).")
    async def approval_request(
        project_id: str,
        action: str,
        reason: str = "",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call_external_session(
            ctx,
            "approval_request",
            {"project_id": project_id, "action": action, "reason": reason},
        )
