"""Governed-coding delivery and missing-evidence phases of ``handle_post_tool_outcome``."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt
from ...core.guards.stop_text import agent_stop_text
from ._loop_evidence_completion import (
    build_missing_evidence_completion_reminder,
    missing_evidence_completion_action,
)
from ._loop_post_tool_coding_delivery import (
    _forced_read_after_failed_governed_coding_edit,
    _governed_coding_evidence_budget_exceeded,
    _governed_coding_expected_paths_ready,
)
from ._loop_post_tool_delivery_progress import _forced_governed_coding_delivery_progress
from ._loop_post_tool_phases import _persist_synthesized_and_return, _PostToolEnv


async def _governed_coding_evidence_budget_outcome(
    env: _PostToolEnv, *, current_step_iterations: int
) -> dict[str, Any] | None:
    evidence_budget = _governed_coding_evidence_budget_exceeded(
        history=env.post_tool_history,
        limit=max(8, int(env.runtime_settings.get("governed_coding_max_evidence_tools_without_delivery") or 14)),
        workflow_contract=env.workflow_contract,
    )
    if not evidence_budget:
        return None
    if not evidence_budget.get("hard_stop"):
        return {
            "action": "append_system_message",
            "system_message": render_prompt("guard.coding.evidence_budget"),
            "current_step_iterations": current_step_iterations,
        }
    stop_content = agent_stop_text("guard.coding.evidence_budget_stop")
    # The assistant_content mirrors the stop message here (not the model output).
    return await _persist_synthesized_and_return(
        env,
        synthesized_content=stop_content,
        source="governed_coding_evidence_budget",
        context_snapshot={
            **dict(env.context_snapshot or {}),
            "governed_coding_evidence_budget": evidence_budget,
        },
        assistant_content=stop_content,
    )


async def _governed_coding_delivery_outcome(
    env: _PostToolEnv, *, current_step_iterations: int
) -> dict[str, Any] | None:
    failed_edit_recovery = _forced_read_after_failed_governed_coding_edit(
        history=env.post_tool_history,
        workflow_contract=env.workflow_contract,
    )
    if failed_edit_recovery:
        return {
            "action": "continue",
            "forced_tool_calls": failed_edit_recovery,
            "current_step_iterations": current_step_iterations,
        }
    delivery_progress = _forced_governed_coding_delivery_progress(
        current_user_message=env.current_user_message,
        history=env.post_tool_history,
        workflow_contract=env.workflow_contract,
    )
    if delivery_progress:
        return {
            "action": "continue",
            "forced_tool_calls": delivery_progress,
            "current_step_iterations": current_step_iterations,
        }
    expected_paths_ready = _governed_coding_expected_paths_ready(
        history=env.post_tool_history,
        workflow_contract=env.workflow_contract,
    )
    if expected_paths_ready:
        expected_paths = ", ".join(f"`{path}`" for path in expected_paths_ready["expected_paths"])
        return {
            "action": "append_system_message",
            "system_message": render_prompt("guard.coding.expected_paths_inspected", expected_paths=expected_paths),
            "current_step_iterations": current_step_iterations,
        }
    return await _governed_coding_evidence_budget_outcome(env, current_step_iterations=current_step_iterations)


def _missing_evidence_followup_outcome(
    env: _PostToolEnv,
    *,
    executed_tool_names: set[str],
) -> dict[str, Any] | None:
    missing_completion_action = missing_evidence_completion_action(
        workflow_contract=env.workflow_contract,
        turn_tool_history=env.turn_tool_history,
        executed_tool_names=executed_tool_names,
    )
    if missing_completion_action is None:
        return None
    return {
        "action": "append_system_message",
        "system_message": build_missing_evidence_completion_reminder(missing_completion_action),
    }
