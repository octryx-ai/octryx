"""The marker a phase turn's workflow contract carries (dependency-free, safe to import from any planner)."""

from __future__ import annotations

from typing import Any

RUN_PHASE_CONTRACT_KEY = "workflow_run_phase"


def is_run_phase_contract(workflow_contract: Any) -> bool:
    return isinstance(workflow_contract, dict) and isinstance(workflow_contract.get(RUN_PHASE_CONTRACT_KEY), dict)


__all__ = ["RUN_PHASE_CONTRACT_KEY", "is_run_phase_contract"]
