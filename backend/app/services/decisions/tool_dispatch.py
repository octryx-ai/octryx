"""Tool dispatch decisions (O2): every governed tool call either counts as allowed or records why it was not."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from ..observability.run_summary import in_app_run_key
from .recorder import (
    GATE_MCP_ACCESS,
    GATE_TOOL_POLICY,
    OUTCOME_DENIED,
    count_allowed,
    record_gate_decision,
)

APPROVAL_REQUIRED = "approval_required"
CEDAR_DENIAL_REASON = "cedar_policy_denied"  # = policy_engine.shadow.REASON_CEDAR_POLICY_DENIED


def _workspace(context: Any) -> str | None:
    project_ids = list(getattr(context, "project_ids", None) or [])
    return str(project_ids[0]) if project_ids else None


def record_tool_dispatch(tool_name: str, context: Any, blocked: dict[str, Any] | None) -> None:
    workspace_id = _workspace(context)
    if blocked is None:
        count_allowed(gate=GATE_TOOL_POLICY, action=tool_name, workspace_id=workspace_id)
        return
    execution = blocked.get("tool_execution") if isinstance(blocked.get("tool_execution"), dict) else {}
    if execution.get("category") == APPROVAL_REQUIRED or execution.get("status") == APPROVAL_REQUIRED:
        return
    if execution.get("reason") == CEDAR_DENIAL_REASON or blocked.get("reason") == CEDAR_DENIAL_REASON:
        return
    policy = str(execution.get("policy") or "")
    request_id = getattr(context, "request_id", None)
    record_gate_decision(
        gate=GATE_MCP_ACCESS if policy.startswith("mcp") else GATE_TOOL_POLICY,
        outcome=OUTCOME_DENIED,
        action=tool_name,
        resource=f"Tool {tool_name}",
        principal=str(getattr(context, "user_id", "") or ""),
        workspace_id=workspace_id,
        session_id=getattr(context, "session_id", None),
        run_key=in_app_run_key(request_id, "") if request_id else None,
        rule=policy or str(execution.get("category") or ""),
        reason=str(execution.get("reason") or execution.get("message") or ""),
    )


def recorded_tool_dispatch(
    checks: Callable[[str, dict, Any], Awaitable[dict[str, Any] | None]],
) -> Callable[[str, dict, Any], Awaitable[dict[str, Any] | None]]:
    @functools.wraps(checks)
    async def run_and_record(tool_name: str, params: dict, context: Any) -> dict[str, Any] | None:
        blocked = await checks(tool_name, params, context)
        record_tool_dispatch(tool_name, context, blocked)
        return blocked

    return run_and_record
