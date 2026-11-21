"""The governed coding agent prompt and the context budget it is rendered within."""

from __future__ import annotations

from typing import Any

from ....models import (
    WorkChangePlan,
    WorkItem,
    WorkItemChangeUnit,
)
from ...content_security.untrusted_fence import fenced_untrusted, new_fence, untrusted_notice
from ...prompt_catalog import render_prompt
from .coding_context_budget import (
    budget_fragment_content,
    build_coding_context_budget_snapshot,
    coding_context_budget_metadata,
)
from .coding_runtime_contract import coding_execution_contract, coding_execution_contract_prompt_lines
from .coding_workspaces import (
    workspace_prompt_lines,
)


def _agent_execution_prompt(
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    units: list[WorkItemChangeUnit],
    pipeline_run: dict[str, Any],
    payload: dict[str, Any],
    workspaces: list[dict[str, Any]] | None = None,
    context_budget: dict[str, Any] | None = None,
) -> str:
    budget = context_budget or _build_agent_context_budget(
        item=item,
        plan=plan,
        payload=payload,
        pipeline_run=pipeline_run,
    )
    from .verification_contract import resolve_verification_contract, verification_contract_prompt_lines

    verification_contract = resolve_verification_contract(plan=plan, units=units)
    # Title and description are written in the work item's source (Jira, ServiceNow): untrusted blocks.
    fence = new_fence()
    return render_prompt(
        "secure_work.coding.execution_prompt",
        state_machine_block=_line_block(_state_machine_prompt_lines(pipeline_run)),
        execution_contract_block=_line_block(
            coding_execution_contract_prompt_lines(_coding_execution_contract_from_run(pipeline_run))
        ),
        source_key=item.source_key,
        title=fenced_untrusted("work item title", item.title, fence),
        source_status=item.source_status or "unknown",
        source_url=item.source_url or "not provided",
        description=(
            f"{untrusted_notice(fence, 'the work item source')}\n"
            f"{fenced_untrusted('work item description', budget_fragment_content(budget, 'description'), fence)}"
        ),
        plan_version=plan.version,
        plan_title=plan.title,
        understood_request=budget_fragment_content(budget, "understood_request"),
        rollback_plan=budget_fragment_content(budget, "rollback_plan"),
        unit_block=_line_block(_unit_lines(units)),
        verification_block=_line_block(verification_contract_prompt_lines(verification_contract)),
        run_id=pipeline_run.get("id"),
        run_status=pipeline_run.get("status"),
        workspace_block=_line_block(workspace_prompt_lines(workspaces or [])),
        restart_line=render_prompt(
            "secure_work.coding.restart_from_scratch"
            if payload.get("restart_from_scratch")
            else "secure_work.coding.normal_start"
        ),
        operator_request=budget_fragment_content(budget, "operator_request"),
    )


def _line_block(lines: list[str]) -> str:
    """Lines for a ``*_block`` placeholder: each line ends with a newline, none when empty."""
    return "".join(f"{line}\n" for line in lines)


def _build_agent_context_budget(
    *,
    item: WorkItem,
    plan: WorkChangePlan,
    payload: dict[str, Any],
    pipeline_run: dict[str, Any],
) -> dict[str, Any]:
    return build_coding_context_budget_snapshot(
        {
            "description": item.description or "",
            "understood_request": plan.understood_request or "",
            "rollback_plan": plan.rollback_plan or render_prompt("secure_work.coding.default_rollback_plan"),
            "operator_request": str(
                payload.get("operator_note") or render_prompt("secure_work.coding.default_operator_request")
            ),
            "state_machine": "\n".join(_state_machine_prompt_lines(pipeline_run)),
        }
    )


def _context_budget_summary(context_budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": context_budget.get("version"),
        "default_char_cap": context_budget.get("default_char_cap"),
        "total_original_chars": context_budget.get("total_original_chars"),
        "total_prompt_chars": context_budget.get("total_prompt_chars"),
        "estimated_prompt_tokens": context_budget.get("estimated_prompt_tokens"),
        "fragments": coding_context_budget_metadata(context_budget),
    }


def _state_machine_prompt_lines(pipeline_run: dict[str, Any]) -> list[str]:
    state_machine = _object((pipeline_run.get("summary") or {}).get("state_machine"))
    if not state_machine:
        return [
            "- version: unavailable",
            "- current_phase: prepared",
            "- next_required_action: prepare_workspace",
            "- required_evidence: workspace_prepared",
        ]
    next_action = _object(state_machine.get("next_action"))
    evidence = _object(state_machine.get("evidence"))
    blockers = [entry for entry in state_machine.get("blockers") or [] if isinstance(entry, dict)]
    lines = [
        f"- version: {state_machine.get('version') or 'unknown'}",
        f"- current_phase: {state_machine.get('phase') or 'unknown'}",
        f"- state_status: {state_machine.get('status') or 'unknown'}",
        f"- next_required_action: {next_action.get('key') or 'unknown'}",
        f"- next_required_action_label: {next_action.get('label') or ''}",
        "- required_evidence: " + ", ".join(str(item) for item in state_machine.get("required_evidence") or []),
    ]
    lines.append(
        "- evidence: "
        + (", ".join(f"{key}={bool(value)}" for key, value in evidence.items()) if evidence else "none")
    )
    if blockers:
        lines.append(
            "- blockers: "
            + "; ".join(
                str(entry.get("code") or entry.get("message") or "blocker").strip() for entry in blockers[:5]
            )
        )
    return lines


def _coding_execution_contract_from_run(pipeline_run: dict[str, Any]) -> dict[str, Any]:
    summary = _object(pipeline_run.get("summary"))
    contract = _object(summary.get("coding_execution_contract"))
    if contract:
        return contract
    return coding_execution_contract(_object(summary.get("state_machine")))


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _unit_lines(units: list[WorkItemChangeUnit]) -> list[str]:
    if not units:
        return [render_prompt("secure_work.coding.no_change_units")]
    lines: list[str] = []
    for unit in units:
        paths = ", ".join(str(path) for path in list(unit.expected_paths_json or [])) or "no paths configured"
        commands = ", ".join(str(command) for command in list(unit.validation_commands_json or [])) or "no commands"
        lines.append(f"- {unit.repository_name} on {unit.branch_name}: {unit.scope or 'approved scope'}")
        lines.append(f"  expected_paths: {paths}")
        lines.append(f"  validation: {commands}")
    return lines
