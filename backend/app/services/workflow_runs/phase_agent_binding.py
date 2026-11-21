"""A phase turn runs as the phase's agent.

The phase resolution carries ``phase_agent`` ``{key, definition_id}``; the turn's agent selection takes it before
any user pick (``agent_selection_source = workflow_phase``). An agent that cannot run (retired, inactive, missing,
ceiling below the class) or a phase without one holds the turn ``needs_configuration`` — never a silent run without
the agent. So does a change phase on the server without the run's prepared working copy (``phase_workspace``). A coding
runtime preference becomes the phase's ``required_model_capability`` unless the phase declares one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ..platform_agents.catalog import RUNTIME_CODING
from .binding import held_resolution
from .graph import PhasedNode
from .phase_agents import agent_refusal, phase_agent_key, phase_class, platform_agent

PHASE_AGENT_RESOLUTION_KEY = "phase_agent"


async def bind_phase_agent(db: AsyncSession, run: WorkflowRun, node: PhasedNode, resolution: dict[str, Any]
                           ) -> dict[str, Any]:
    key = phase_agent_key(node.config)
    if not key:
        # A phase without an agent holds the turn: the agent of a phase is never guessed.
        return held_resolution(run, profile_status="needs_configuration",
                               reason="The phase names no agent (phase_without_agent): publish a version whose "
                                      "phases name their agent and start a new run.")
    row = await platform_agent(db, key)
    reason = agent_refusal(row, needed_class=phase_class(node.config))
    if reason:
        return held_resolution(run, profile_status="needs_configuration",
                               reason=f"The phase's agent '{key}' cannot run ({reason}).")
    from .phase_workspace import phase_copy_refusal

    # A phase on the server works in the run's prepared working copy; without the one it needs it never runs elsewhere.
    no_copy = await phase_copy_refusal(db, run, phase_class(node.config))
    if no_copy:
        return held_resolution(run, profile_status="needs_configuration", reason=no_copy)
    resolution[PHASE_AGENT_RESOLUTION_KEY] = {"key": key, "definition_id": row.definition_id,
                                              "revision_id": row.revision_id}
    contract = resolution.get("workflow_contract")
    if row.runtime_preference == RUNTIME_CODING and isinstance(contract, dict) and not contract.get(
            "required_model_capability"):
        contract["required_model_capability"] = RUNTIME_CODING
    return resolution


def phase_agent_of(policy_resolution: Any) -> dict[str, str] | None:
    """The phase agent a turn's routing resolution names, or ``None``."""
    if not isinstance(policy_resolution, dict):
        return None
    value = policy_resolution.get(PHASE_AGENT_RESOLUTION_KEY)
    if isinstance(value, dict) and value.get("definition_id"):
        return {"key": str(value.get("key") or ""), "definition_id": str(value["definition_id"])}
    return None
