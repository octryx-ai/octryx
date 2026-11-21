"""The per-turn decision of an agent's tool surface and the dispatch refusal it implies.

Callers (tool registry, turn dispatch, run context) import it from here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_tool_surface_contract import (
    DECISION_SOURCE,
    REASON_CODE_INVALID,
    REASON_CODE_STEP_CONFLICT,
    REASON_CODE_TEXT_ONLY,
    REASON_CODE_WORKFLOW_CONFLICT,
    REFUSAL_POLICY,
    REQUIREMENT_METADATA_KEY,
    TOOL_SURFACE_GOVERNED,
    TOOL_SURFACE_NONE,
    denies_tools,
    payload_tool_surface,
    tool_surface_step_conflict,
)


@dataclass(frozen=True, slots=True)
class ToolSurfaceDecision:
    """Whether a turn of this agent may run, given its declared surface."""

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


def evaluate_agent_tool_surface(
    agent_definition: Mapping[str, Any] | None, *, workflow_tools_declared: bool
) -> ToolSurfaceDecision:
    """Decide a turn before any model call.

    *workflow_tools_declared* is true when the turn's selected definition or selected workflow
    declares a tool surface.
    """
    surface = payload_tool_surface(agent_definition)
    if surface == TOOL_SURFACE_GOVERNED:
        return ToolSurfaceDecision(surface, True)
    if surface != TOOL_SURFACE_NONE:
        return ToolSurfaceDecision(
            surface,
            False,
            "This agent's tool setting is not valid; an admin must choose policy-governed tools or No tools.",
            REASON_CODE_INVALID,
        )
    if workflow_tools_declared:
        return ToolSurfaceDecision(
            surface,
            False,
            "This agent is set to No tools (text only), but the selected workflow needs tools. "
            "Choose a different agent or change the agent's tool setting.",
            REASON_CODE_WORKFLOW_CONFLICT,
        )
    step_conflict = tool_surface_step_conflict(surface, (agent_definition or {}).get("steps") or [])
    if step_conflict:
        return ToolSurfaceDecision(surface, False, step_conflict, REASON_CODE_STEP_CONFLICT)
    return ToolSurfaceDecision(surface, True)


def apply_tool_surface_decision_to_profile(
    execution_profile: dict[str, Any] | None, decision: ToolSurfaceDecision
) -> dict[str, Any]:
    """Record the decision on the profile; a refused one blocks an ``allowed`` profile as ``needs_configuration``.

    A profile that is already blocked keeps its own, earlier decision.
    """
    # Lazy: the snapshot/payload modules import this contract and must not pull in workflow routing.
    from app.services.execution_profile_status import EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION

    from .execution_profile_status import EXECUTION_PROFILE_STATUS_ALLOWED

    profile = dict(execution_profile or {})
    if decision.tool_surface == TOOL_SURFACE_GOVERNED:
        return profile
    requirements = dict(profile.get("requirements") or {})
    requirements[REQUIREMENT_METADATA_KEY] = decision.to_metadata()
    profile["requirements"] = requirements
    if decision.allowed or profile.get("status") != EXECUTION_PROFILE_STATUS_ALLOWED:
        return profile
    profile["status"] = EXECUTION_PROFILE_STATUS_NEEDS_CONFIGURATION
    profile["decision_source"] = DECISION_SOURCE
    profile["reason"] = decision.reason
    profile["reason_code"] = decision.reason_code
    return profile


def tool_surface_dispatch_refusal(tool_name: str, context: Any) -> dict[str, Any] | None:
    """Refuse every tool for an agent that does not declare ``governed``; ``None`` allows dispatch.

    The refusal is the typed ``denied_by_policy`` tool result every dispatch gate returns, so audit,
    tool history and the model see it like any other policy refusal.
    """
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
