"""Seed texts of the prompt catalog, one module per area."""

from __future__ import annotations

from ..contract import PromptKeySpec
from . import (
    analysis,
    coding,
    context,
    evidence,
    evidence_guard,
    guard,
    judge,
    knowledge,
    loop,
    office,
    personality,
    run,
    secure_work,
    tool_guard_results,
    workflow_capability,
    workflow_proposal,
)

SEED_MODULES = (
    run,
    evidence,
    evidence_guard,
    personality,
    context,
    coding,
    workflow_capability,
    workflow_proposal,
    loop,
    guard,
    tool_guard_results,
    analysis,
    secure_work,
    knowledge,
    judge,
    office,
)


def all_seed_specs() -> tuple[PromptKeySpec, ...]:
    return tuple(spec for module in SEED_MODULES for spec in module.SPECS)


__all__ = ["SEED_MODULES", "all_seed_specs"]
