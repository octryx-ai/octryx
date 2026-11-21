"""Generic evidence-completion checks for no-tool follow-up turns.

An action applies by its tool conditions only; the prompt never decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....services.prompt_catalog import render_prompt


@dataclass(frozen=True)
class MissingEvidenceAction:
    tool_name: str
    evidence_label: str
    guidance: str
    successful_prerequisites: tuple[str, ...] = ()


def missing_evidence_completion_action(
    *,
    workflow_contract: dict[str, Any] | None,
    turn_tool_history: list[dict[str, Any]],
    executed_tool_names: set[str],
) -> MissingEvidenceAction | None:
    contract = workflow_contract if isinstance(workflow_contract, dict) else {}
    if not contract:
        return None

    available_contract_tools = _contract_tool_names(contract)
    for action in _required_actions(contract):
        tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
        if not tool_name or tool_name not in available_contract_tools:
            continue
        if _has_successful_tool_result(turn_tool_history, tool_name):
            continue
        if not _action_condition_matches(
            action,
            turn_tool_history=turn_tool_history,
            executed_tool_names=executed_tool_names,
        ):
            continue
        prerequisites = tuple(
            tool
            for tool in _string_list(action.get("after_successful_tools"))
            if _has_successful_tool_result(turn_tool_history, tool)
        )
        return MissingEvidenceAction(
            tool_name=tool_name,
            evidence_label=str(action.get("evidence_label") or action.get("label") or tool_name).strip(),
            guidance=str(action.get("guidance") or "").strip(),
            successful_prerequisites=prerequisites,
        )
    return None


def build_missing_evidence_completion_reminder(action: MissingEvidenceAction) -> str:
    prerequisite_text = (
        render_prompt(
            "guard.evidence.prerequisites", prerequisite_tools=", ".join(action.successful_prerequisites)
        )
        if action.successful_prerequisites
        else ""
    )
    guidance_text = render_prompt("guard.evidence.guidance", guidance=action.guidance) if action.guidance else ""
    return render_prompt(
        "guard.evidence.missing_reminder",
        evidence_label=action.evidence_label,
        tool_name=action.tool_name,
        prerequisite_text=prerequisite_text,
        guidance_text=guidance_text,
    )


def _required_actions(contract: dict[str, Any]) -> list[dict[str, Any]]:
    completion = contract.get("evidence_completion")
    if isinstance(completion, dict) and isinstance(completion.get("required_actions"), list):
        return [item for item in completion["required_actions"] if isinstance(item, dict)]

    actions: list[dict[str, Any]] = []
    source_steps = contract.get("source_steps")
    if not isinstance(source_steps, list):
        return actions
    for step in source_steps:
        if not isinstance(step, dict):
            continue
        condition = step.get("required_when") or step.get("completion_required_when")
        if not isinstance(condition, dict):
            continue
        actions.append(
            {
                "tool": step.get("tool"),
                "evidence_label": step.get("evidence_label") or step.get("label"),
                "guidance": step.get("guidance"),
                **condition,
            }
        )
    return actions


def _action_condition_matches(
    action: dict[str, Any],
    *,
    turn_tool_history: list[dict[str, Any]],
    executed_tool_names: set[str],
) -> bool:
    if action.get("required") is False:
        return False

    after_all = _string_list(action.get("after_successful_tools"))
    if after_all and not all(_has_successful_tool_result(turn_tool_history, tool) for tool in after_all):
        return False

    after_any = _string_list(action.get("after_any_successful_tools"))
    if after_any and not any(_has_successful_tool_result(turn_tool_history, tool) for tool in after_any):
        return False

    unless_successful = _string_list(action.get("unless_successful_tools"))
    if any(_has_successful_tool_result(turn_tool_history, tool) for tool in unless_successful):
        return False

    unless_executed = _string_list(action.get("unless_executed_tools"))
    normalized_executed = {str(name or "").strip() for name in executed_tool_names}
    if any(tool in normalized_executed for tool in unless_executed):
        return False

    return bool(after_all or after_any or action.get("required") is True)


def _contract_tool_names(contract: dict[str, Any]) -> set[str]:
    names = set(_string_list(contract.get("allowed_tools")))
    source_steps = contract.get("source_steps")
    if isinstance(source_steps, list):
        names.update(
            str(step.get("tool") or "").strip()
            for step in source_steps
            if isinstance(step, dict) and str(step.get("tool") or "").strip()
        )
    return names


def _has_successful_tool_result(turn_tool_history: list[dict[str, Any]], tool_name: str) -> bool:
    for item in turn_tool_history or []:
        if not isinstance(item, dict) or str(item.get("tool_name") or "").strip() != tool_name:
            continue
        result = item.get("result") if isinstance(item.get("result"), dict) else {}
        if result and not result.get("error"):
            return True
    return False


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
