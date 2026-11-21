"""The marker a phase turn's workflow contract carries (dependency-free, safe to import from any planner).

``phase_definition`` stamps ``workflow_run_phase`` into the contract of every phase turn of a phased run. A phase
reuses a family ``workflow_id`` (``knowledge_request``, ``coding_change_tdd``, …) for its contract message only:
its tool surface is the phase's own ``tool_policy`` and its completion is the run's phase checks. No code-registry
workflow definition that shares the id plans, narrows, forces or completes a phase turn.
"""

from __future__ import annotations

from typing import Any

RUN_PHASE_CONTRACT_KEY = "workflow_run_phase"


def is_run_phase_contract(workflow_contract: Any) -> bool:
    """True when the contract is a phase turn's contract of a workflow run."""
    return isinstance(workflow_contract, dict) and isinstance(workflow_contract.get(RUN_PHASE_CONTRACT_KEY), dict)


__all__ = ["RUN_PHASE_CONTRACT_KEY", "is_run_phase_contract"]
