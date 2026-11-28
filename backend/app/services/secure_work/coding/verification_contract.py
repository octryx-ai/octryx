"""Verification contract for coding agent executions, resolved from explicit, approved sources."""

from __future__ import annotations

from typing import Any

from ...prompt_catalog import render_prompt

VERIFICATION_CONTRACT_KEY = "verification_contract"
GOVERNED_CODING_WORKFLOW_ID = "coding_change_tdd"


def is_governed_coding_contract(workflow_contract: Any) -> bool:
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

    # Sources are alternatives, not additive: a merged contract can demand tools the host lacks and never pass
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
