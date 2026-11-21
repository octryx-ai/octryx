"""Execution helpers for the standard agent loop driver."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from typing import Any

from ....services.knowledge_salvage import KNOWLEDGE_TOOL_NAMES
from ....services.prompt_catalog import render_prompt

_KNOWLEDGE_PROGRESS_EXTENSION_LIMIT = 8


# The loop state names the iteration helpers read and update, in the order the state lists them.
_ITERATION_STATE_NAMES: tuple[str, ...] = (
    "active_steps",
    "current_step_index",
    "current_step_iterations",
    "current_step_tool_activity",
    "current_step_wrapup_forced",
    "covered_evidence_axes",
    "covered_summary_domains",
    "duplicate_no_tool_response_count",
    "executed_tool_names",
    "repeated_previous_step_summary_count",
    "required_domains",
    "step_tool_history",
    "step_tool_history_index",
    "tdd_cycle_state",
    "tdd_cycle_step_index",
    "turn_diff_tracker",
    "turn_tool_history",
    "existing_thread_context",
    "workflow_artifact_ready_for_final_response",
    "workflow_contract",
    "workflow_final_answer_prompted",
    "forced_tool_calls",
    "latest_repo_state",
    "last_no_tool_response_content",
    "last_no_tool_response_signature",
    "last_no_tool_response_step_index",
    "total_tokens_in",
    "total_tokens_out",
    "consecutive_non_progress_response_count",
    "consecutive_transitional_response_count",
    "consecutive_coding_no_execution_count",
)


def build_standard_loop_iteration_context(
    *,
    scope: dict[str, Any],
    tool_domain_config: dict[str, Any] | None,
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None, dict[str, Any] | None], set[str]],
    build_runtime_cycle_shared: Callable[[dict[str, Any]], dict[str, Any]],
    build_outcome_cycle_shared: Callable[[dict[str, Any]], dict[str, Any]],
    summarize_threshold: int,
) -> dict[str, Any]:
    """The mutable iteration state and the shared collaborators, all read by name from the loop scope."""
    runtime_cycle_shared = build_runtime_cycle_shared(scope)
    outcome_cycle_shared = build_outcome_cycle_shared({**scope, "summarize_threshold": summarize_threshold})
    messages = scope["messages"]
    state: dict[str, Any] = {
        "messages": messages,
        "request_messages": messages,
        **{name: scope[name] for name in _ITERATION_STATE_NAMES},
    }

    return {
        "state": state,
        "runtime_cycle_shared": runtime_cycle_shared,
        "outcome_cycle_shared": outcome_cycle_shared,
        "summary_domains_for_result": (
            lambda tool_name, result: summary_domains_satisfied_by_result(
                tool_name,
                result,
                tool_domain_config,
            )
        ),
    }


def _has_any_tool_activity(state: dict[str, Any]) -> bool:
    return bool(state.get("turn_tool_history") or state.get("executed_tool_names"))


def _workflow_id(state: dict[str, Any]) -> str:
    contract = state.get("workflow_contract")
    if not isinstance(contract, dict):
        return ""
    return str(contract.get("workflow_id") or "").strip().lower()


def _knowledge_tool_target(item: dict[str, Any]) -> tuple[str, str] | None:
    tool_name = str(item.get("tool_name") or "").strip()
    if tool_name not in KNOWLEDGE_TOOL_NAMES:
        return None
    result = item.get("result") if isinstance(item.get("result"), dict) else {}
    if result.get("error"):
        return None
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    if not params and isinstance(item.get("parameters"), dict):
        params = item["parameters"]
    for key in ("knowledge_id", "evidence_key", "id", "key", "query", "category", "page_id"):
        value = str(params.get(key) or result.get(key) or "").strip()
        if value:
            return tool_name, value
    return tool_name, "<result>"


def _knowledge_progress_score(state: dict[str, Any]) -> int:
    targets: set[tuple[str, str]] = set()
    for item in state.get("turn_tool_history") or []:
        if not isinstance(item, dict):
            continue
        target = _knowledge_tool_target(item)
        if target:
            targets.add(target)
    return len(targets)


def _should_extend_for_knowledge_progress(
    state: dict[str, Any],
    *,
    base_max_iterations: int,
    effective_max_iterations: int,
) -> bool:
    if _workflow_id(state) != "knowledge_request":
        return False
    if effective_max_iterations >= base_max_iterations + _KNOWLEDGE_PROGRESS_EXTENSION_LIMIT:
        return False
    progress_score = _knowledge_progress_score(state)
    if progress_score <= 0:
        return False
    previous_score = int(state.get("knowledge_iteration_extension_score") or 0)
    if progress_score <= previous_score:
        return False
    state["knowledge_iteration_extension_score"] = progress_score
    state["knowledge_iteration_extension_count"] = int(state.get("knowledge_iteration_extension_count") or 0) + 1
    return True


def _append_final_iteration_instruction(state: dict[str, Any]) -> None:
    if state.get("final_iteration_instruction_added"):
        return
    state["final_iteration_instruction_added"] = True
    messages = state.get("messages")
    if not isinstance(messages, list):
        return
    messages.append(
        {
            "role": "system",
            "content": render_prompt("guard.final_iteration"),
        }
    )


def _prepare_last_iteration(
    state: dict[str, Any],
    *,
    iteration: int,
    max_iterations: int,
    effective_max_iterations: int,
) -> int:
    """On the last iteration with tool activity: extend a progressing knowledge turn, else ask for the answer."""
    if iteration == effective_max_iterations - 1 and _has_any_tool_activity(state):
        if _should_extend_for_knowledge_progress(
            state,
            base_max_iterations=max_iterations,
            effective_max_iterations=effective_max_iterations,
        ):
            effective_max_iterations += 1
        else:
            _append_final_iteration_instruction(state)
    if iteration == effective_max_iterations - 1 and _has_any_tool_activity(state):
        _append_final_iteration_instruction(state)
    return effective_max_iterations


async def stream_standard_loop_iterations(
    *,
    max_iterations: int,
    state: dict[str, Any],
    runtime_settings: dict[str, Any] | None,
    max_iterations_for_agent_step: Callable[[dict[str, Any] | None], int],
    runtime_cycle_shared: dict[str, Any],
    outcome_cycle_shared: dict[str, Any],
    summary_domains_for_result: Callable[[str, dict[str, Any] | None], set[str]],
    run_standard_loop_iteration: Callable[..., Any],
    emit_loop_final_fallback: Callable[..., Any],
    db: Any,
    session_id: str,
    event_factory: Callable[..., Any],
    build_runtime_error_salvage_message: Callable[..., Any],
) -> AsyncGenerator[Any, None]:
    effective_max_iterations = max_iterations
    iteration = 0
    while iteration < effective_max_iterations:
        effective_max_iterations = _prepare_last_iteration(
            state,
            iteration=iteration,
            max_iterations=max_iterations,
            effective_max_iterations=effective_max_iterations,
        )
        iteration_result = await run_standard_loop_iteration(
            iteration=iteration,
            state=state,
            runtime_settings=runtime_settings,
            max_iterations_for_agent_step=max_iterations_for_agent_step,
            runtime_cycle_shared=runtime_cycle_shared,
            outcome_cycle_shared=outcome_cycle_shared,
            summary_domains_for_result=summary_domains_for_result,
            checkpoint_db=db,
            checkpoint_session_id=session_id,
        )
        for event in iteration_result.get("events") or []:
            if event is not None:
                yield event
        if iteration_result.get("action") == "return":
            return
        iteration += 1

    from ...loops.control._loop_terminal_phase import record_iteration_ceiling

    await record_iteration_ceiling(db=db, session_id=session_id, state=state, shared=runtime_cycle_shared)
    yield await emit_loop_final_fallback(
        db=db,
        session_id=session_id,
        request_messages=state["request_messages"],
        total_tokens_in=state["total_tokens_in"],
        total_tokens_out=state["total_tokens_out"],
        event_factory=event_factory,
        _build_runtime_error_salvage_message=build_runtime_error_salvage_message,
    )


__all__ = [
    "build_standard_loop_iteration_context",
    "stream_standard_loop_iterations",
]
