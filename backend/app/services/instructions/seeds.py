"""The shipped instructions: currently none.

A shipped instruction is bound to the workflow it serves; ``ensure_default_instructions`` creates a missing one
as a published seed and never overwrites an admin edit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class InstructionSeed:
    key: str
    title: str
    workflow_key: str
    body: str


# No shipped instruction.
SEEDS: tuple[InstructionSeed, ...] = ()

__all__ = ["SEEDS", "InstructionSeed"]
