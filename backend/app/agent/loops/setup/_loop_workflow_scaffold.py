"""Synthetic workflow step scaffold — shared by turn setup and mid-turn adoption.

The scaffold (synthetic workflow agent, e.g. the Diagram Designer, plus its
enabled steps with per-step tool allowlists and evidence-first instructions)
is built at loop setup. A workflow selected mid-turn via
``select_workflow`` gets the exact same scaffold so fetch workflows (e.g.
code-structure diagrams with ``prepare_bitbucket_repository``) run end-to-end;
the capability/change gating stays inside the shared builder pieces.
"""

from __future__ import annotations

from typing import Any

from app.services.workflow_contracts.agent_definition import build_workflow_agent_definition

from ..control._loop_self_review import _ensure_terminal_self_review_step


def build_workflow_step_scaffold(
    *,
    workflow_contract: dict[str, Any] | None,
    agent_definition: dict[str, Any] | None,
    capability_type: str | None,
) -> dict[str, Any]:
    """Build the synthetic workflow agent + active steps for a contract.

    Identical precedence to turn setup: an explicit user/workspace agent
    definition wins; the synthetic workflow agent is injected only when no
    agent is active.
    """
    synthetic_workflow_agent = build_workflow_agent_definition(workflow_contract)
    injected_workflow_agent = False
    if synthetic_workflow_agent and not agent_definition:
        agent_definition = synthetic_workflow_agent
        injected_workflow_agent = True

    active_steps = (
        [step for step in (agent_definition or {}).get("steps", []) if step.get("isEnabled")]
        if agent_definition
        else []
    )
    active_steps = _ensure_terminal_self_review_step(
        active_steps,
        capability_type=capability_type,
        agent_definition=agent_definition,
    )
    return {
        "agent_definition": agent_definition,
        "active_steps": active_steps,
        "injected_workflow_agent": injected_workflow_agent,
        "synthetic_workflow_agent": synthetic_workflow_agent,
    }


__all__ = ["build_workflow_step_scaffold"]
