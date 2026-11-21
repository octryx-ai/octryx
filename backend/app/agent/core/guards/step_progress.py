"""Step progress guards: when a plan step is stuck, and how many iterations a step may take."""

from __future__ import annotations

from typing import Any

from ....services.prompt_catalog import render_prompt
from .response_guards import get_step_allowed_tools, get_step_field


def detect_step_tool_stagnation(step: dict[str, Any] | None, history: list[dict[str, Any]]) -> str | None:
    if not step or len(history) < 4:
        return None
    step_name = str(step.get("name") or "").strip() or "current step"
    step_type = str(get_step_field(step, "stepType", "step_type", "") or "").strip().lower()
    recent_history = history[-6:]
    recent_tool_names = [str(item.get("tool_name") or "").strip() for item in recent_history]
    if len(recent_tool_names) >= 5 and len(set(recent_tool_names[-5:])) == 1:
        return render_prompt("guard.step.stagnation_same_tool", step_name=step_name, tool_name=recent_tool_names[-1])

    blocked_attempts = 0
    for item in recent_history:
        result = item.get("result")
        if isinstance(result, dict):
            error_text = str(result.get("error") or "").lower()
            if "not allowed in the current step" in error_text:
                blocked_attempts += 1
    if blocked_attempts >= 2:
        return render_prompt("guard.step.stagnation_off_contract", step_name=step_name)

    if step_type == "analysis":
        repo_evidence_tools = {
            "prepare_bitbucket_repository",
            "git_change_summary",
            "analyze_workspace_repository",
            "list_workspace_git_commits",
        }
        repo_evidence_collected = any(
            str(item.get("tool_name") or "").strip() in repo_evidence_tools for item in history
        )
        repeated_jira_searches = sum(
            1 for item in recent_history if str(item.get("tool_name") or "").strip() == "search_jira_tickets"
        )
        if repo_evidence_collected and repeated_jira_searches >= 4:
            return render_prompt("guard.step.stagnation_jira", step_name=step_name)
    return None


def max_iterations_for_agent_step(step: dict[str, Any] | None) -> int:
    if not step:
        return 8
    allowed_tools = set(get_step_allowed_tools(step))
    step_type = str(get_step_field(step, "stepType", "step_type", "") or "").strip().lower()
    step_config = get_step_field(step, "stepConfig", "step_config", None)
    limit = 8
    if step_type == "tdd_cycle":
        limit = max(limit, 24)
    if {
        "prepare_bitbucket_repository",
        "list_repository_readme_status",
    }.intersection(allowed_tools):
        limit = max(limit, 20)
    if "analyze_workspace_repository" in allowed_tools:
        limit = max(limit, 20)
    if step_type in {"analysis", "knowledge"} and {
        "list_workspace_directory",
        "read_workspace_file",
    }.intersection(allowed_tools):
        limit = max(limit, 12)
    if isinstance(step_config, dict):
        try:
            explicit_limit = int(step_config.get("max_iterations"))
        except (TypeError, ValueError):
            explicit_limit = 0
        if explicit_limit > 0:
            return max(1, min(explicit_limit, 32))
    return limit
