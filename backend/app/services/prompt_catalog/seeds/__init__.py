"""Seed texts of the prompt catalog, one module per area.

These modules are the only code copy of agent-facing prompt texts. Adding a key means
adding a :class:`~app.services.prompt_catalog.contract.PromptKeySpec` here; the call
site renders it through the turn's prompt set (``render_prompt``).

An area module may contain several sub-modules when one would grow past the module size
budget; a large area is split by key prefix (``workflow``, ``workflow_lines``, ...).
"""

from __future__ import annotations

from ..contract import PromptKeySpec
from . import (
    analysis,
    answer,
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
    research_delegation,
    run,
    secure_work,
    system,
    tool_guard,
    workflow,
    workflow_capability,
    workflow_lines,
    workflow_proposal,
)

SEED_MODULES = (
    system,
    run,
    evidence,
    evidence_guard,
    personality,
    context,
    coding,
    workflow,
    workflow_lines,
    workflow_capability,
    workflow_proposal,
    loop,
    guard,
    analysis,
    research_delegation,
    secure_work,
    tool_guard,
    knowledge,
    judge,
    answer,
    office,
)


def all_seed_specs() -> tuple[PromptKeySpec, ...]:
    return tuple(spec for module in SEED_MODULES for spec in module.SPECS)


__all__ = ["SEED_MODULES", "all_seed_specs"]
