"""Self-review step helpers for the standard agent loop."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt
from ....tools.tool_names import ToolName
from ...core.guards.response_guards import get_step_allowed_tools


def _step_declares_self_review(step: dict[str, Any]) -> bool:
    step_type = str(step.get("stepType") or step.get("step_type") or "").strip().lower()
    if step_type in {"self_review", "tdd_cycle"}:
        return True
    return False


def _agent_requires_terminal_self_review(
    active_steps: list[dict[str, Any]],
    *,
    capability_type: str,
    agent_definition: dict[str, Any] | None,
) -> bool:
    if capability_type != "change" or not active_steps:
        return False
    if bool((agent_definition or {}).get("requireSelfReview") or (agent_definition or {}).get("require_self_review")):
        return True
    repo_change_tools = {
        "apply_workspace_patch",
        "write_workspace_file",
        "delete_workspace_file",
        "commit_and_push_repository_branch",
        "create_pull_request",
    }
    artifact_workflow_tools = {
        "build_word_template_script",
        "build_presentation_script",
        "build_excel_template_script",
        "validate_office_document",
        "get_office_document_info",
    }
    for step in active_steps:
        step_type = str(step.get("stepType") or step.get("step_type") or "").strip().lower()
        allowed_tools = {str(tool).strip() for tool in get_step_allowed_tools(step) if str(tool).strip()}
        if step_type == "tdd_cycle":
            return False
        if allowed_tools & artifact_workflow_tools:
            return False
        if allowed_tools & repo_change_tools:
            return True
    return False


def _ensure_terminal_self_review_step(
    active_steps: list[dict[str, Any]],
    *,
    capability_type: str,
    agent_definition: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not _agent_requires_terminal_self_review(
        active_steps, capability_type=capability_type, agent_definition=agent_definition
    ):
        return active_steps
    if any(_step_declares_self_review(step) for step in active_steps):
        return active_steps
    synthetic_step = {
        "name": "Self Review",
        "stepType": "self_review",
        "instructions": render_prompt("guard.self_review.step_instructions"),
        "successCriteria": render_prompt("guard.self_review.step_success"),
        "allowedTools": [
            "run_test_suite",
            "lint_and_format_workspace",
            "run_sast_suite",
            "self_review_workspace_diff",
            "build_pull_request_description",
        ],
        "stepConfig": {"tool_use": "required"},
        "isEnabled": True,
        "syntheticSelfReview": True,
    }
    return [*active_steps, synthetic_step]


def _is_self_review_step(step: dict[str, Any] | None) -> bool:
    return str((step or {}).get("stepType") or (step or {}).get("step_type") or "").strip().lower() == "self_review"


def _is_self_review_step_complete(step: dict[str, Any] | None, step_tool_history: list[dict[str, Any]]) -> bool:
    allowed_tools = {str(tool).strip().lower() for tool in get_step_allowed_tools(step or {}) if str(tool).strip()}
    required_review_tools = {"self_review_workspace_diff", "build_pull_request_description"}
    if not (allowed_tools & required_review_tools):
        return True
    saw_review = False
    saw_pr_description = False
    for item in step_tool_history:
        tool_name = str((item or {}).get("tool_name") or "").strip().lower()
        result = (item or {}).get("result") if isinstance(item, dict) else {}
        if tool_name == ToolName.SELF_REVIEW_WORKSPACE_DIFF and isinstance(result, dict) and result.get("ready_for_pr"):
            saw_review = True
        if tool_name == ToolName.BUILD_PULL_REQUEST_DESCRIPTION:
            saw_pr_description = True
    return saw_review and saw_pr_description


def _build_incomplete_self_review_reminder(step: dict[str, Any]) -> str:
    step_name = str((step or {}).get("name") or "").strip() or "current step"
    return render_prompt("guard.self_review.incomplete_reminder", step_name=step_name)


def _model_role_for_current_subtask(
    *,
    current_step: dict[str, Any] | None,
    current_step_for_runtime: dict[str, Any] | None,
    step_tool_history: list[dict[str, Any]],
) -> str:
    step_type = str((current_step or {}).get("stepType") or (current_step or {}).get("step_type") or "").strip().lower()
    tdd_phase = str((current_step_for_runtime or {}).get("tddCyclePhase") or "").strip().lower()
    last_tool = step_tool_history[-1] if step_tool_history else {}
    last_tool_name = str((last_tool or {}).get("tool_name") or "").strip().lower()
    last_tool_result = (last_tool or {}).get("result") if isinstance(last_tool, dict) else {}
    if step_type == "self_review":
        if (
            last_tool_name == ToolName.SELF_REVIEW_WORKSPACE_DIFF
            and isinstance(last_tool_result, dict)
            and last_tool_result.get("ready_for_pr")
        ):
            return "pr_description"
        return "self_review"
    if step_type == "tdd_cycle":
        if tdd_phase == "write_tests":
            return "test_generation"
        if tdd_phase == "make_green":
            return "code_generation"
        if tdd_phase == "refactor":
            return "lint_fix"
        if tdd_phase == "security_review":
            return "security_review"
        if tdd_phase == "self_review":
            if (
                last_tool_name == ToolName.SELF_REVIEW_WORKSPACE_DIFF
                and isinstance(last_tool_result, dict)
                and last_tool_result.get("ready_for_pr")
            ):
                return "pr_description"
            return "self_review"
    if step_type in {"change", "tooling"}:
        return "code_generation"
    return ""


__all__ = [
    "_step_declares_self_review",
    "_agent_requires_terminal_self_review",
    "_ensure_terminal_self_review_step",
    "_is_self_review_step",
    "_is_self_review_step_complete",
    "_build_incomplete_self_review_reminder",
    "_model_role_for_current_subtask",
]
