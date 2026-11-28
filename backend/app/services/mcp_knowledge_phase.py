"""Which Knowledge MCP tools a launcher session bound to a running workflow run sees in its phase."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from .mcp_governed_knowledge_tools import mcp_caller

PHASE_RUN_TOOLS = frozenset({"workflow_run_status", "workflow_action_request"})


async def outside_run_phase(
    server: FastMCP, db: AsyncSession, workspace_id: str, names: list[str], authenticated_context: Any
) -> frozenset[str]:
    # Listing only the phase's tools keeps device turns small; calls outside the phase are refused anyway.
    allowed = await run_phase_allowed(server, db, workspace_id, authenticated_context)
    return hidden_in_phase(names, allowed) if allowed else frozenset()


async def run_phase_allowed(
    server: FastMCP, db: AsyncSession, workspace_id: str, authenticated_context: Any
) -> set[str] | None:
    from ..models import User
    from .mcp_workflow_run_session import _gateway
    from .workflow_runs.octryx.contract import run_contract
    from .workflow_runs.records import active_run_for_session

    try:
        caller = mcp_caller(server.get_context(), authenticated_context)
    except (HTTPException, ValueError):
        return None
    user = await db.get(User, caller.user_id) if caller.user_id else None
    gateway = await _gateway(db, caller, user, workspace_id) if user is not None else None
    run = await active_run_for_session(db, gateway.id) if gateway is not None else None
    if run is None or run.status != "running":
        return None
    phase = (await run_contract(db, run, principal=user, session=gateway)).get("phase") or {}  # an item's own phase
    tools = dict(phase.get("tools") or {})
    return (set(tools.get("allow") or []) - set(tools.get("deny") or [])) or None


def hidden_in_phase(names: list[str], allowed: set[str]) -> frozenset[str]:
    return frozenset(name for name in names if name not in allowed and name not in PHASE_RUN_TOOLS)
