"""The shipped instructions: currently none."""

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
