"""Artifact and report phases of ``handle_post_tool_outcome``.

Each phase returns an action dict when it terminates the turn, or ``None`` to fall through to the next phase.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..control._loop_coding_completion import build_direct_coding_completion_message
from ._loop_post_tool_phases import _persist_synthesized_and_return, _PostToolEnv


async def _jira_sprint_bundle_outcome(
    env: _PostToolEnv,
    *,
    agent_definition: Any,
    current_step: dict[str, Any] | None,
    current_step_index: int,
    active_steps: list[dict[str, Any]],
    latest_successful_tool_result_from_results: Callable[[list[dict[str, Any]], str], dict[str, Any] | None],
    is_jira_sprint_planner: Callable[[dict[str, Any] | None], bool],
    build_jira_sprint_bundle_report: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any] | None:
    jira_sprint_bundle_result = latest_successful_tool_result_from_results(
        env.tool_results, "create_jira_sprint_bundle"
    )
    if (
        jira_sprint_bundle_result
        and is_jira_sprint_planner(agent_definition)
        and current_step
        and current_step_index == len(active_steps) - 1
    ):
        synthesized_content = build_jira_sprint_bundle_report(jira_sprint_bundle_result)
        if synthesized_content:
            return await _persist_synthesized_and_return(
                env, synthesized_content=synthesized_content, source="create_jira_sprint_bundle"
            )
    return None


async def _coding_completion_outcome(
    env: _PostToolEnv,
    *,
    current_step: dict[str, Any] | None,
    tdd_cycle_state: dict[str, Any] | None,
    is_tdd_cycle_step: Callable[[dict[str, Any] | None], bool],
    is_tdd_cycle_complete: Callable[[dict[str, Any] | None], bool],
) -> dict[str, Any] | None:
    coding_completion_message = (
        build_direct_coding_completion_message(tool_results=env.tool_results, turn_tool_history=env.turn_tool_history)
        if (
            (not current_step and not env.workflow_contract)
            or (
                current_step
                and is_tdd_cycle_step(current_step)
                and tdd_cycle_state is not None
                and is_tdd_cycle_complete(tdd_cycle_state)
            )
        )
        else None
    )
    if not coding_completion_message:
        return None
    return await _persist_synthesized_and_return(
        env, synthesized_content=coding_completion_message, source="run_test_suite"
    )


async def _single_tool_report_outcome(
    env: _PostToolEnv,
    *,
    missing_domains: set[str],
    has_followup_steps: bool,
    agent_definition: Any,
    format_recent_bitbucket_commits_report: Callable[[dict[str, Any]], str],
) -> dict[str, Any] | None:
    tool_results = env.tool_results
    if (
        len(tool_results) == 1
        and tool_results[0].get("tool_name") == "list_recent_bitbucket_commits"
        and "error" not in (tool_results[0].get("result") or {})
        and not missing_domains
        and not has_followup_steps
    ):
        synthesized_content = format_recent_bitbucket_commits_report(tool_results[0]["result"])
        return await _persist_synthesized_and_return(
            env, synthesized_content=synthesized_content, source="list_recent_bitbucket_commits"
        )
    return None
