"""Dispatch of a published workflow capability tool (``run_flow_*``) after the registry's governed checks.

The capability runs as a DAG flow run in a Workspace; a start without one is the typed ``needs_configuration`` /
``workspace_required`` tool result, with nothing written (``services/flow_orchestration/start_scope``).
"""

from __future__ import annotations

from typing import Any

from .context import ToolContext
from .results import annotate_tool_result_payload, safe_tool_error_message


async def dispatch_flow_capability_tool(tool_name: str, params: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    from ..services.flow_capabilities import execute_flow_capability_tool
    from ..services.workflow_runs.records import WorkflowRunError

    flow_db = getattr(context, "db", None)
    if flow_db is None:
        return annotate_tool_result_payload(
            tool_name,
            {"error": "Workflow capability execution requires a database-bound tool context."},
            category="validation_error",
            reason="missing_database_context",
            policy="workflow_capability_context",
        )
    try:
        return annotate_tool_result_payload(
            tool_name,
            await execute_flow_capability_tool(flow_db, tool_name=tool_name, params=params, context=context),
        )
    except WorkflowRunError as refused:
        return annotate_tool_result_payload(
            tool_name,
            {"error": str(refused), "state": refused.state, "reason": refused.code, "tool_name": tool_name},
            category="validation_error",
            reason=refused.code,
            policy="workflow_capability_workspace",
        )
    except Exception as exc:
        return annotate_tool_result_payload(
            tool_name,
            {"error": f"Workflow capability execution failed: {safe_tool_error_message(exc)}", "tool_name": tool_name},
            category="execution_error",
            reason="workflow_capability_exception",
        )


__all__ = ["dispatch_flow_capability_tool"]
