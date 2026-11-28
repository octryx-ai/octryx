"""The run's own Work item, read-only, for a run-bound octryx-claude session without ``work:manage``. Least privilege:
only the run's own item."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import async_session_factory
from ..models import User, WorkItem
from .knowledge.sources.repository_snapshot.session_target import bound_gateway_session
from .mcp_auto_session import record_mcp_tool_activity
from .mcp_governed_knowledge import McpCaller, resolve_mcp_workspace
from .mcp_knowledge_observability import audit_mcp_knowledge_tool_call, enforce_mcp_knowledge_rate_limit

RUN_BOUND_WORK_TOOLS = frozenset({"work_item_context", "work_item_create", "work_item_note"})
RUN_BOUND_WRITE_TOOLS = frozenset({"work_item_create", "work_item_note"})
RUN_WORK_ITEM_SCOPE = "workflow:read"
RUN_WORK_WRITE_SCOPE = "workflow:execute"
PHASE_REFUSED_DETAIL = "The workflow run's current phase does not allow this Work tool"
REFUSED_DETAIL = ("OAuth grant lacks required scope: work:manage (without it, only the Work item of this "
                  "session's workflow run is readable)")


def run_bound_work_tool(tool_name: str, scopes: tuple[str, ...]) -> bool:
    if tool_name in RUN_BOUND_WRITE_TOOLS:
        return RUN_WORK_WRITE_SCOPE in scopes
    return tool_name in RUN_BOUND_WORK_TOOLS and RUN_WORK_ITEM_SCOPE in scopes


async def run_work_item(db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str,
                        requested: Any) -> WorkItem:
    # Only the run's own item, from a session following the run; 403 otherwise.
    return (await _run_and_item(db, caller=caller, user=user, workspace_id=workspace_id, requested=requested))[1]


async def _phase_allows(db: AsyncSession, run: Any, tool_name: str) -> bool:
    from .workflow_runs.graph import graph_for_run

    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    if node is None or node.kind != "phase":
        return False
    allowlist = dict(dict(node.config or {}).get("tool_policy") or {}).get("allowlist") or []
    return tool_name in allowlist


async def _run_and_item(db: AsyncSession, *, caller: McpCaller, user: User, workspace_id: str,
                        requested: Any) -> tuple[Any, WorkItem]:
    from .workflow_runs.access import run_access
    from .workflow_runs.records import active_run_for_session

    gateway = (await bound_gateway_session(db, user_id=user.id, workspace_id=workspace_id,
                                           session_key=caller.session_key) if caller.session_key else None)
    run = await active_run_for_session(db, gateway.id) if gateway is not None else None
    item = await db.get(WorkItem, run.work_item_id) if run is not None and run.work_item_id else None
    text = str(requested or "").strip()
    if (item is None or run.project_id != workspace_id or await run_access(db, run, user) == "none"
            or (text and text not in (item.id, item.source_key, run.ticket_key))):
        raise HTTPException(status_code=403, detail=REFUSED_DETAIL)
    return run, item


async def _write(db: AsyncSession, run: Any, item: WorkItem, user: User, tool_name: str,
                 arguments: dict[str, Any]) -> dict[str, Any]:
    from .secure_work.platform_items import add_work_item_note, create_platform_work_item

    if tool_name == "work_item_note":
        return await add_work_item_note(db, item=item, note=str(arguments.get("note") or ""), current_user=user)
    from ..tools.secure_work_impl._work_item_tools import _open_twin

    twin = await _open_twin(db, run.project_id, arguments)
    if twin is not None:
        return {"id": twin.id, "source_key": twin.source_key, "already_existed": True,
                "note": f"{twin.source_key} already exists with this title; do not create it again, "
                        "continue with the next item."}
    created = await create_platform_work_item(
        db, current_user=user, project_id=run.project_id, title=str(arguments.get("title") or ""),
        description=str(arguments.get("description") or ""), issue_type=str(arguments.get("issue_type") or "task"),
        epic_key=str(arguments.get("epic_key") or ""),
        labels=arguments.get("labels") if isinstance(arguments.get("labels"), list) else [],
        priority=str(arguments.get("priority") or "normal"))
    return {"id": created.id, "source_key": created.source_key, "issue_type": created.issue_type,
            "epic_key": created.epic_key, "project_id": created.project_id}


async def call_run_bound_work_tool(caller: McpCaller, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from .secure_work.platform_item_context import build_work_item_context

    workspace = resolve_mcp_workspace(caller)
    if not isinstance(workspace, str):
        raise HTTPException(status_code=403, detail=REFUSED_DETAIL)
    async with async_session_factory() as db:
        user = await db.get(User, caller.user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="MCP OAuth user is not active")
        await enforce_mcp_knowledge_rate_limit(api_key_id=caller.grant_id, user_id=user.id, tool_name=tool_name)
        audit = {"user_id": user.id, "api_key_id": caller.grant_id, "api_key_project_id": workspace,
                 "tool_name": tool_name, "arguments": {"work_item": str(arguments.get("work_item") or "")[:120],
                                                       "title": str(arguments.get("title") or "")[:120]},
                 "transport": caller.transport}
        writes = tool_name in RUN_BOUND_WRITE_TOOLS
        try:
            run, item = await _run_and_item(db, caller=caller, user=user, workspace_id=workspace,
                                            requested="" if tool_name == "work_item_create" else
                                            arguments.get("work_item"))
            if writes and not await _phase_allows(db, run, tool_name):
                raise HTTPException(status_code=403, detail=PHASE_REFUSED_DETAIL)
        except HTTPException as exc:
            await audit_mcp_knowledge_tool_call(db, **audit, status_value="denied", error_detail=str(exc.detail))
            await db.commit()
            raise
        result = (await _write(db, run, item, user, tool_name, arguments) if writes else
                  await build_work_item_context(db, item=item, include_session_digests=False))
        await record_mcp_tool_activity(db, user=user, grant_id=caller.grant_id, client_name=caller.client_name,
                                       tool_name=tool_name, arguments=audit["arguments"])
        await audit_mcp_knowledge_tool_call(db, **audit, result={"work_item_id": item.id}, status_value="success")
        await db.commit()
        return {**result, "access": "workflow_run"}


__all__ = ["RUN_BOUND_WORK_TOOLS", "RUN_BOUND_WRITE_TOOLS", "call_run_bound_work_tool", "run_bound_work_tool",
           "run_work_item"]
