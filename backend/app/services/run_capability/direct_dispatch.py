"""The run capability check for workers that call a tool implementation directly.

Registry dispatch (``tools/registry._run_governed_tool_checks``) refuses a tool above the run's
class. A few workers call one fixed tool implementation without the registry (the Teams reply's
Jira comment, the governed Knowledge tools on MCP, the Office live validation). They pass the same
check here, with the same refusal, before the tool runs.
"""

from __future__ import annotations

from typing import Any

from ...tools.results import annotate_tool_result_payload
from .escalation import CAPABILITY_REFUSAL_POLICY, capability_dispatch_refusal


async def execute_with_capability_check(tool: Any, params: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run ``tool`` only when the context's run capability covers it; otherwise the refusal."""
    tool_name = str(getattr(tool, "name", "") or "")
    refusal = capability_dispatch_refusal(tool_name, context)
    if refusal is not None:
        return annotate_tool_result_payload(
            tool_name, refusal, category="denied_by_policy", policy=CAPABILITY_REFUSAL_POLICY
        )
    return await tool.execute(params, context)


__all__ = ["execute_with_capability_check"]
