"""The Knowledge MCP server's own tools: session ingest and approval requests."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context


def register_core_tools(server: Any, *, call_external_session: Any) -> None:
    _register_external_session_tools(server, call_external_session=call_external_session)


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
