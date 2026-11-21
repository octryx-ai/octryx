"""Verification contract for coding agent executions.

Each run gets its own contract, resolved from EXPLICIT, approved sources.
The stack intelligence comes from the planning LLM (it proposes stack-
appropriate validation commands in the work plan — terraform plan for IaC,
mvn test for Java, pytest for Python); the human approves them with the plan;
execution is then BOUND to the approved contract. No hardcoded per-stack
rules, no unreviewed runtime guessing.

Resolution: the highest-trust source that defines commands WINS — sources are
alternatives, not additive (every command carries its source for the audit
trail). Merged trust levels could combine environment-honest unit commands with
an approved plan's ``terraform plan``/``helm lint``, a contract that never goes
green on a host without those binaries. A contract the agent cannot satisfy is a broken gate,
not a stricter one.

1. Change-unit ``validation_commands`` — human-scoped, highest trust.
2. Repository-profile test/lint commands — per-repo defaults.
3. Work-plan ``validation_plan`` — LLM-proposed at plan time, approved with
   the plan.
4. Empty contract → the step uses ``run_test_suite`` auto-detection.
"""

from __future__ import annotations

from typing import Any

from ...prompt_catalog import render_prompt

VERIFICATION_CONTRACT_KEY = "verification_contract"
GOVERNED_CODING_WORKFLOW_ID = "coding_change_tdd"


def is_governed_coding_contract(workflow_contract: Any) -> bool:
    """Explicit governed signal: the workflow contract carries the approved
    verification contract for governed coding runs."""
    return bool(
        isinstance(workflow_contract, dict)
        and workflow_contract.get("workflow_id") == GOVERNED_CODING_WORKFLOW_ID
        and workflow_contract.get(VERIFICATION_CONTRACT_KEY)
    )

SOURCE_CHANGE_UNIT = "change_unit"
SOURCE_REPOSITORY_PROFILE = "repository_profile"
SOURCE_PLAN_VALIDATION = "plan_validation_plan"


def resolve_verification_contract(
    *,
    plan: Any,
    units: list[Any],
    profile_commands: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build the verification contract for one execution run."""
    commands: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(command: Any, source: str) -> None:
        text = str(command or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        commands.append({"command": text, "source": source})

    for unit in units or []:
        for command in list(getattr(unit, "validation_commands_json", None) or []):
            _add(command, SOURCE_CHANGE_UNIT)

    if not commands:
        for key in ("test_commands", "lint_commands"):
            for command in (profile_commands or {}).get(key) or []:
                _add(command, SOURCE_REPOSITORY_PROFILE)

    if not commands:
        plan_validation = getattr(plan, "validation_plan_json", None) or getattr(plan, "validation_plan", None)
        for entry in list(plan_validation or []):
            if isinstance(entry, dict):
                _add(entry.get("command"), SOURCE_PLAN_VALIDATION)

    contract: dict[str, Any] = {
        "commands": commands,
        "resolved_from": sorted({entry["source"] for entry in commands}),
    }
    # Approved acceptance criteria ride with the contract so the runtime and
    # the delivery report can show WHAT each command proves.
    criteria = list(
        getattr(plan, "acceptance_criteria_json", None) or getattr(plan, "acceptance_criteria", None) or []
    )
    if criteria:
        contract["acceptance_criteria"] = [entry for entry in criteria if isinstance(entry, dict)]
    return contract


def verification_contract_prompt_lines(contract: dict[str, Any] | None) -> list[str]:
    commands = list((contract or {}).get("commands") or [])
    if not commands:
        return [render_prompt("secure_work.verification.none_resolved")]
    lines = [render_prompt("secure_work.verification.header")]
    lines.extend(
        f"- {entry['command']}  [source: {entry['source']}]" for entry in commands
    )
    criteria = [entry for entry in (contract or {}).get("acceptance_criteria") or [] if isinstance(entry, dict)]
    if criteria:
        lines.append(render_prompt("secure_work.verification.criteria_header"))
        lines.extend(
            f"- {entry.get('id')}: {entry.get('text')}" for entry in criteria
        )
    lines.append(render_prompt("secure_work.verification.closing"))
    return lines


def apply_verification_contract_to_workflow_contract(
    workflow_contract: dict[str, Any] | None,
    session_metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Attach the run's verification contract (stored on the session by the
    secure-work execution start) to the workflow contract, so the step machine
    can build its success criterion from it. Follows the same applier pattern
    as the research policy."""
    if not isinstance(workflow_contract, dict) or not workflow_contract:
        return workflow_contract
    execution = (session_metadata or {}).get("secure_work_execution")
    if not isinstance(execution, dict):
        return workflow_contract
    applied = workflow_contract
    contract = execution.get(VERIFICATION_CONTRACT_KEY)
    if isinstance(contract, dict) and contract.get("commands"):
        applied = {**applied, VERIFICATION_CONTRACT_KEY: contract}
    # Provider context for the delivery hand-off step (source-control provider
    # of the change units, ticket system of the work item).
    delivery = execution.get("delivery")
    if isinstance(delivery, dict) and delivery:
        applied = {**applied, "delivery": delivery}
    # Approved expected paths from the change units (via the prepared
    # workspaces): loop guards read them from the contract, never from the
    # prompt text.
    expected_paths: list[str] = []
    for workspace in execution.get("workspaces") or []:
        if not isinstance(workspace, dict):
            continue
        evidence = workspace.get("evidence") if isinstance(workspace.get("evidence"), dict) else {}
        for path in evidence.get("approved_expected_paths") or []:
            text = str(path or "").strip()
            if text and text not in expected_paths:
                expected_paths.append(text)
    if expected_paths:
        applied = {**applied, "expected_paths": expected_paths}
    return applied


__all__ = [
    "GOVERNED_CODING_WORKFLOW_ID",
    "VERIFICATION_CONTRACT_KEY",
    "apply_verification_contract_to_workflow_contract",
    "is_governed_coding_contract",
    "resolve_verification_contract",
    "verification_contract_prompt_lines",
]
