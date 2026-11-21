"""The inputs of the standard agent loop and the name scope its iteration helpers read from."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..context.run_context import PreparedAgentRun

# The names each source contributes to the loop scope, exactly the ones the loop binds from it.
_PREPARED_SCOPE_NAMES: tuple[str, ...] = (
    "capability_type",
    "current_turn_content",
    "tool_definitions",
    "tool_context",
    "runtimes",
    "existing_thread_context",
    "context_plan",
    "system_prompt",
    "personality_prompt",
    "memory_prompt",
    "skills_prompt",
    "summary_context_msgs",
    "history",
    "messages",
    "history_count",
    "system_context",
    "runtime_settings",
    "tool_domain_config",
)
_LOOP_STATE_SCOPE_NAMES: tuple[str, ...] = (
    "agent_definition",
    "active_steps",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "covered_evidence_axes",
    "covered_summary_domains",
    "duplicate_no_tool_response_count",
    "executed_tool_names",
    "injected_workflow_agent",
    "max_iterations",
    "provider_reasoning_effort",
    "repeated_previous_step_summary_count",
    "request_analysis",
    "required_domains",
    "step_tool_history",
    "step_tool_history_index",
    "tdd_cycle_state",
    "tdd_cycle_step_index",
    "turn_diff_tracker",
    "turn_tool_history",
)
_RUNTIME_INIT_SCOPE_NAMES: tuple[str, ...] = (
    "request_timeout_seconds",
    "duplicate_no_tool_response_count",
    "repeated_previous_step_summary_count",
    "consecutive_transitional_response_count",
    "consecutive_coding_no_execution_count",
    "consecutive_non_progress_response_count",
    "provider_max_tokens",
    "total_tokens_in",
    "total_tokens_out",
    "forced_tool_calls",
    "latest_repo_state",
    "last_no_tool_response_content",
    "last_no_tool_response_signature",
    "last_no_tool_response_step_index",
    "workflow_artifact_ready_for_final_response",
    "workflow_contract",
    "workflow_final_answer_prompted",
)


@dataclass(kw_only=True)
class StandardLoopInputs:
    """The arguments of ``run_standard_agent_loop``; unknown or missing names raise ``TypeError``."""

    prepared: PreparedAgentRun
    session_id: str
    user_id: str
    db: AsyncSession
    runtime_target_id: str | None
    thinking_level: str | None
    agent_definition: dict | None
    max_iterations: int | None
    map_reasoning_effort: Callable[[str | None], str | None]
    max_completion_tokens_for_run: Callable[[str, str | None, dict | None], int | None]
    max_iterations_for_agent_step: Callable[[dict[str, Any] | None], int]
    filter_tool_definitions: Callable[[list[dict], list[str] | None], list[dict]]
    build_current_step_prompt: Callable[[dict, int, int, str | None], str]
    normalize_runtime_chat_result: Callable[
        [tuple[Any, ...]],
        tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]],
    ]
    chat_with_runtime_fallback: Callable[..., Any]
    is_transitional_assistant_response: Callable[[str, list[dict[str, Any]] | None, bool], bool]
    is_transitional_tool_call_preamble: Callable[[str, list[dict[str, Any]] | None], bool]
    is_non_substantive_assistant_response: Callable[[str, list[dict[str, Any]] | None], bool]
    allows_noop_step_completion: Callable[[dict[str, Any] | None, str], bool]
    build_required_tool_reminder: Callable[[dict[str, Any]], str]
    build_stalled_step_message: Callable[[dict[str, Any]], str]
    assistant_no_tool_response_signature: Callable[[str], str | None]
    assistant_no_tool_response_similarity: Callable[[str, str], float]
    looks_like_step_completion_summary: Callable[[str], bool]
    execute_tool_call_for_turn: Callable[..., Any]
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]]
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]]
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None], set[str]]
    execute_tool: Callable[[str, dict[str, Any], Any], Any]
    record_usage_event: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    persist_synthesized_tool_assistant: Callable[..., Any]
    format_repository_noop_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_repository_knowledge_sync_report: Callable[[list[dict[str, Any]]], str | None]
    format_recent_bitbucket_commits_report: Callable[[dict[str, Any]], str]
    has_pending_approval_result: Callable[[list[dict[str, Any]]], bool]
    event_factory: Callable[..., Any]


def standard_loop_scope(
    module_names: Mapping[str, Any],
    inputs: StandardLoopInputs,
    *,
    loop_state: dict[str, Any],
    runtime_init: dict[str, Any],
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Every name the iteration helpers may read; a later source wins, as a later binding would.

    ``module_names`` are the loop's named helpers (``standard_loop._LOOP_HELPERS``), then come the call's
    arguments, the prepared run's fields, the loop state, the runtime state and the bootstrapped messages.
    """
    prepared = inputs.prepared
    return {
        **module_names,
        **{field.name: getattr(inputs, field.name) for field in fields(inputs)},
        **{name: getattr(prepared, name) for name in _PREPARED_SCOPE_NAMES},
        **{name: loop_state[name] for name in _LOOP_STATE_SCOPE_NAMES},
        "loop_state": loop_state,
        **{name: runtime_init[name] for name in _RUNTIME_INIT_SCOPE_NAMES},
        "runtime_init": runtime_init,
        "messages": messages,
    }
