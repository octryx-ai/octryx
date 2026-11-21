"""Handle and dispatch runtime turn outcomes for the standard loop."""

from __future__ import annotations

from typing import Any

from ._loop_outcome_cycle_inputs import OutcomeCycleInputs


async def run_outcome_cycle(inputs: OutcomeCycleInputs) -> dict[str, Any]:
    turn_outcome = await inputs.handle_turn_outcome(inputs)
    outcome_dispatch = await inputs.dispatch_turn_outcome(turn_outcome, inputs)
    return outcome_dispatch


__all__ = ["run_outcome_cycle"]
