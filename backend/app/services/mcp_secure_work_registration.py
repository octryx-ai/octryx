"""Tool names and signatures of the secure-work MCP tool surface (handlers: ``mcp_secure_work_tools``)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context


def register_secure_work_tools(server: Any, call: Any) -> None:
    # Registration order is the order ``tools/list`` shows.
    _register_item_lookup_tools(server, call)
    _register_item_record_tools(server, call)
    _register_item_progress_tools(server, call)
    _register_change_plan_tools(server, call)
    _register_delivery_tools(server, call)


def _register_item_lookup_tools(server: Any, call: Any) -> None:
    @server.tool(description="Find a work item by Jira source key or platform id (state, status, links).")
    async def work_item_find(work_item: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "work_item_find", {"work_item": work_item})

    @server.tool(
        description=(
            "List OPEN work items to pick up (the actionable backlog): non-terminal states by default, "
            "each with readiness signals (has_plan, sessions). Filter by project_id, state, assignee, "
            "mine=true, issue_type, source_type, limit. Ready-to-work (planned) items are sorted first."
        )
    )
    async def work_item_list(
        project_id: str = "",
        state: str = "",
        assignee: str = "",
        mine: bool = False,
        issue_type: str = "",
        source_type: str = "",
        limit: int = 25,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "work_item_list",
            {
                "project_id": project_id,
                "state": state,
                "assignee": assignee,
                "mine": mine,
                "issue_type": issue_type,
                "source_type": source_type,
                "limit": limit,
            },
        )


def _register_item_record_tools(server: Any, call: Any) -> None:
    @server.tool(
        description=(
            "Create a PLATFORM-ONLY work item (never synced to Jira or any tracker): "
            "issue_type epic|task|bug|improvement|spike; pass epic_key to assign a task to an epic. "
            "Use for agent working tasks - Jira stays the human task list."
        )
    )
    async def work_item_create(
        project_id: str,
        title: str,
        description: str = "",
        issue_type: str = "task",
        epic_key: str = "",
        labels: list[str] | None = None,
        priority: str = "normal",
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "work_item_create",
            {
                "project_id": project_id,
                "title": title,
                "description": description,
                "issue_type": issue_type,
                "epic_key": epic_key,
                "labels": labels or [],
                "priority": priority,
            },
        )

    @server.tool(
        description=(
            "Full handover context for a work item: description, epic children, state history, "
            "latest change plan, progress notes, and linked sessions WITH their conversation "
            "digests. Call this first when continuing work another agent started. A session that follows a "
            "workflow run reads its run's own Work item (ticket_key) here, without session digests."
        )
    )
    async def work_item_context(
        work_item: str, include_session_digests: bool = True, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "work_item_context",
            {"work_item": work_item, "include_session_digests": include_session_digests},
        )


def _register_item_progress_tools(server: Any, call: Any) -> None:
    @server.tool(
        description=(
            "Link an ingested CLI session to a work item (client_session_id as reported to "
            "session_ingest, e.g. claude-code-<uuid>). The session digest then appears in "
            "work_item_context for the next worker."
        )
    )
    async def work_item_link_session(
        work_item: str, client_session_id: str, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "work_item_link_session",
            {"work_item": work_item, "client_session_id": client_session_id},
        )

    @server.tool(
        description=(
            "Append a progress note to a work item (what was done, what is open, gotchas) - "
            "the handover breadcrumbs for the next worker."
        )
    )
    async def work_item_note(
        work_item: str, note: str, claim_epoch: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(ctx, "work_item_note", {"work_item": work_item, "note": note, "claim_epoch": claim_epoch})

    @server.tool(
        description="Plan change units for a work item (repository scope, expected paths, validation commands)."
    )
    async def change_units_plan(
        work_item: str, units: list[dict[str, Any]], claim_epoch: int | None = None, ctx: Context | None = None
    ) -> dict[str, Any]:
        return await call(
            ctx, "change_units_plan", {"work_item": work_item, "units": units, "claim_epoch": claim_epoch}
        )


def _register_change_plan_tools(server: Any, call: Any) -> None:
    @server.tool(
        description=(
            "Generate a change plan from the work item's change units; payload may carry "
            "acceptance_criteria mapping ticket clauses to validation commands."
        )
    )
    async def change_plan_generate(
        work_item: str,
        payload: dict[str, Any] | None = None,
        claim_epoch: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "change_plan_generate",
            {"work_item": work_item, "payload": payload or {}, "claim_epoch": claim_epoch},
        )

    @server.tool(
        description=(
            "Decide a change plan (approve/reject/request_clarification). Approval is blocked while "
            "any acceptance criterion lacks an enforceable validation command."
        )
    )
    async def change_plan_decide(
        change_plan_id: str,
        action: str,
        reason: str = "",
        human_verified_criteria: list[str] | None = None,
        claim_epoch: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "change_plan_decide",
            {
                "change_plan_id": change_plan_id,
                "action": action,
                "reason": reason,
                "human_verified_criteria": human_verified_criteria or [],
                "claim_epoch": claim_epoch,
            },
        )


def _register_delivery_tools(server: Any, call: Any) -> None:
    @server.tool(
        description="Redeclare a work item after a declined PR: supersedes plans and units, keeps the audit trail."
    )
    async def work_item_redeclare(work_item: str, reason: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "work_item_redeclare", {"work_item": work_item, "reason": reason})

    @server.tool(description="Start the governed coding agent for a work item's approved plan and change units.")
    async def coding_agent_start(
        work_item: str,
        change_unit_ids: list[str] | None = None,
        restart_from_scratch: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "coding_agent_start",
            {
                "work_item": work_item,
                "change_unit_ids": change_unit_ids or [],
                "restart_from_scratch": restart_from_scratch,
            },
        )

    @server.tool(
        description=(
            "Transition a work item's lifecycle state (default workflow when none given); "
            "mapped Jira transitions execute as configured."
        )
    )
    async def work_item_transition(
        work_item: str,
        to_state: str,
        reason: str = "",
        workflow_id: str = "",
        claim_epoch: int | None = None,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        return await call(
            ctx,
            "work_item_transition",
            {"work_item": work_item, "to_state": to_state, "reason": reason, "workflow_id": workflow_id,
             "claim_epoch": claim_epoch},
        )

    @server.tool(description="Coding observability for a work item: sessions, tool calls, token usage, audit events.")
    async def coding_observability(work_item: str, ctx: Context | None = None) -> dict[str, Any]:
        return await call(ctx, "coding_observability", {"work_item": work_item})
