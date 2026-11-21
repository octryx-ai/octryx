"""Acceptance-criteria coverage gate for change plans.

Why this exists: a delivered change can be green against its verification
contract yet incomplete against the work item (e.g. a
ticket clause "clean also the config for prod and nonprod" that never becomes
a validation command cannot be enforced by the completion gate). Prose
instructions inside unit descriptions are not enforceable; only validation
commands are.

The contract this module enforces at plan-approval time:

- Every requirement clause of the work item is an acceptance criterion
  (LLM-proposed with the plan, or operator-provided, or derived one-per-unit).
- Every criterion maps to at least one ENFORCEABLE validation command of the
  plan (placeholder entries such as ``manual_required`` do not count).
- A criterion the approver explicitly takes over is allowed only through the
  decision payload (``human_verified_criteria``) and is recorded in the
  decision audit trail — an explicit, attributed state instead of silent
  narrowing.
- Anything else blocks approval with the uncovered criteria listed.
"""

from __future__ import annotations

from typing import Any

# validation_plan entries with these sources are placeholders, not proofs.
PLACEHOLDER_COMMAND_SOURCES = {"manual_required"}

# Plan types whose approval is always coverage-gated, even without criteria.
COVERAGE_GATED_PLAN_TYPES = {"coding_change", "configuration_change"}


def normalize_acceptance_criteria(raw: Any) -> list[dict[str, Any]]:
    """Validate and normalize proposed criteria to the stored shape."""
    criteria: list[dict[str, Any]] = []
    for index, entry in enumerate(list(raw or []), start=1):
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        commands = [
            str(command).strip()
            for command in (entry.get("validation_commands") or [])
            if str(command or "").strip()
        ]
        criteria.append(
            {
                "id": str(entry.get("id") or f"AC{index}").strip(),
                "text": text,
                "source": str(entry.get("source") or "work_item").strip(),
                "validation_commands": commands,
            }
        )
    return criteria


def derive_unit_acceptance_criteria(change_units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One criterion per change unit, covered by the unit's own commands.

    Fallback for unit-based plans without operator-provided criteria: it makes
    the existing unit scope reviewable in the same matrix and blocks approval
    for units that carry no validation command at all.
    """
    return normalize_acceptance_criteria(
        [
            {
                "id": f"AC{index}",
                "text": str(unit.get("scope") or unit.get("repository_name") or "").strip(),
                "source": "change_unit",
                "validation_commands": list(unit.get("validation_commands") or []),
            }
            for index, unit in enumerate(change_units, start=1)
        ]
    )


def enforceable_commands(validation_plan: list[Any]) -> set[str]:
    commands: set[str] = set()
    for entry in validation_plan or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("source") or "").strip() in PLACEHOLDER_COMMAND_SOURCES:
            continue
        command = str(entry.get("command") or "").strip()
        if command:
            commands.add(command)
    return commands


def evaluate_acceptance_coverage(
    criteria: list[dict[str, Any]],
    validation_plan: list[Any],
) -> dict[str, Any]:
    """Per-criterion coverage report against the plan's enforceable commands."""
    enforceable = enforceable_commands(validation_plan)
    evaluated: list[dict[str, Any]] = []
    uncovered_ids: list[str] = []
    for criterion in criteria:
        matched = [command for command in criterion.get("validation_commands") or [] if command in enforceable]
        covered = bool(matched)
        evaluated.append({**criterion, "covered": covered, "matched_commands": matched})
        if not covered:
            uncovered_ids.append(str(criterion.get("id")))
    return {
        "criteria": evaluated,
        "uncovered_ids": uncovered_ids,
        "enforceable_commands": sorted(enforceable),
    }


def acceptance_coverage_blockers(
    *,
    plan_type: str,
    criteria: list[dict[str, Any]],
    validation_plan: list[Any],
    has_change_units: bool,
    human_verified_ids: list[str],
) -> list[str]:
    """Reasons the plan may NOT be approved; empty means approvable.

    Gated when the plan carries criteria, is a coding/configuration plan, or
    snapshots change units. Non-gated plans (analysis, documentation, plans
    without criteria) approve without this gate.
    """
    gated = bool(criteria) or plan_type in COVERAGE_GATED_PLAN_TYPES or has_change_units
    if not gated:
        return []
    if not criteria:
        return [
            "Plan defines no acceptance criteria: every requirement clause of the "
            "work item must map to an enforceable validation command before approval."
        ]
    verified = {str(value).strip() for value in human_verified_ids if str(value or "").strip()}
    report = evaluate_acceptance_coverage(criteria, validation_plan)
    unknown_verified = verified - {str(criterion.get("id")) for criterion in criteria}
    blockers = [
        f"human_verified_criteria references unknown criterion id '{value}'" for value in sorted(unknown_verified)
    ]
    for criterion in report["criteria"]:
        if criterion["covered"] or str(criterion.get("id")) in verified:
            continue
        blockers.append(
            f"{criterion['id']}: \"{criterion['text']}\" has no enforceable validation command "
            "(add one to the plan, or take it over explicitly via human_verified_criteria)"
        )
    return blockers


__all__ = [
    "COVERAGE_GATED_PLAN_TYPES",
    "PLACEHOLDER_COMMAND_SOURCES",
    "acceptance_coverage_blockers",
    "derive_unit_acceptance_criteria",
    "enforceable_commands",
    "evaluate_acceptance_coverage",
    "normalize_acceptance_criteria",
]
