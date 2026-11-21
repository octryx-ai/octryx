"""Observational turn classification for agent-loop iterations.

The loop records each iteration's subtask role, coding discipline, reasoning task type
and reasoning stage in the trace. They are observations only: since R3 no rule here
selects, reorders or replaces a runtime. A turn's runtime comes from the explicit turn
runtime selection (``services/session/turn_runtime_selection``) and changes within a
turn only through the provider fallback's explicit, logged failover.
"""

from __future__ import annotations

from typing import Any


def coding_discipline_for_role(
    *,
    capability_type: str,
    current_step: dict[str, Any] | None,
    current_subtask_role: str,
) -> str:
    """Derive the coding discipline for the current turn.

    Default derivation policy (first matching rule wins): analysis/diagnosis
    steps on a change capability are repo intelligence, review-flavored
    roles/steps are review, test generation is test-fix, code changes are
    edit, everything else is planning.
    """
    step_type = str((current_step or {}).get("stepType") or (current_step or {}).get("step_type") or "").strip().lower()
    normalized_role = str(current_subtask_role or "").strip().lower()
    if capability_type == "change" and step_type in {"analysis", "diagnosis"}:
        return "repo-intelligence"
    if normalized_role in {"self_review", "security_review", "pr_description"} or step_type == "self_review":
        return "review"
    if normalized_role == "test_generation":
        return "test-fix"
    if normalized_role in {"code_generation", "lint_fix"} or capability_type == "change":
        return "edit"
    return "planning"


def reasoning_task_type_for_turn(
    *,
    capability_type: str,
    current_step: dict[str, Any] | None,
    current_step_for_runtime: dict[str, Any] | None,
    context_plan: Any,
) -> str:
    """Derive the reasoning task type for the current turn.

    Default derivation policy (first matching rule wins): review steps/TDD
    phases are review, change capabilities and change-flavored steps are
    change, everything else is diagnosis. The context plan's route is explicit;
    no route reads the prompt, so none maps to a summary task.
    """
    step_type = str((current_step or {}).get("stepType") or (current_step or {}).get("step_type") or "").strip().lower()
    tdd_phase = str((current_step_for_runtime or {}).get("tddCyclePhase") or "").strip().lower()
    if step_type == "self_review" or tdd_phase in {"security_review", "self_review"}:
        return "review"
    if capability_type == "change" or step_type in {"change", "tooling", "tdd_cycle"}:
        return "change"
    return "diagnosis"


def reasoning_stage_for_turn(
    *,
    capability_type: str,
    current_step: dict[str, Any] | None,
    current_subtask_role: str,
) -> str:
    """Derive the reasoning stage for the current turn.

    Default derivation policy (first matching rule wins): review roles/steps
    verify; any change capability, active step, or execution role executes;
    everything else plans.
    """
    step_type = str((current_step or {}).get("stepType") or (current_step or {}).get("step_type") or "").strip().lower()
    normalized_role = str(current_subtask_role or "").strip().lower()
    if step_type == "self_review" or normalized_role in {"self_review", "security_review"}:
        return "verifier"
    if (
        capability_type == "change"
        or step_type
        or normalized_role in {"code_generation", "test_generation", "lint_fix"}
    ):
        return "executor"
    return "planner"


__all__ = [
    "coding_discipline_for_role",
    "reasoning_stage_for_turn",
    "reasoning_task_type_for_turn",
]
