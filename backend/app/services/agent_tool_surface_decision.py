"""The per-turn decision of an agent's tool surface and the dispatch refusal it implies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .agent_tool_surface_contract import (
    REASON_CODE_TEXT_ONLY,
    REFUSAL_POLICY,
    denies_tools,
)


@dataclass(frozen=True, slots=True)
class ToolSurfaceDecision:
    tool_surface: str
    allowed: bool
    reason: str = ""
    reason_code: str = ""

    def to_metadata(self) -> dict[str, Any]:
        return {
            "tool_surface": self.tool_surface,
            "allowed": self.allowed,
            "reason": self.reason or None,
            "reason_code": self.reason_code or None,
        }


def tool_surface_dispatch_refusal(tool_name: str, context: Any) -> dict[str, Any] | None:
    # The refusal is the typed ``denied_by_policy`` result every dispatch gate returns.
    if not denies_tools(getattr(context, "agent_definition", None)):
        return None
    from ..tools.results import annotate_tool_result_payload

    return annotate_tool_result_payload(
        tool_name,
        {
            "error": f"Tool '{tool_name}' was not run: this agent is set to No tools (text only).",
            "status": "denied",
            "tool_name": tool_name,
        },
        category="denied_by_policy",
        reason=REASON_CODE_TEXT_ONLY,
        policy=REFUSAL_POLICY,
    )
