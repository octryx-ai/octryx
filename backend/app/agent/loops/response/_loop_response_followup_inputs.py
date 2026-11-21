"""Inputs and the shared continue-or-stop step of ``handle_followup_response_guards``."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....services.prompt_catalog import render_prompt

_StepCheck = Callable[[dict[str, Any] | None], bool]

_NON_SUBSTANTIVE_DRAFT_PATTERN = re.compile(
    r"^\s*(?:i\s+(?:will|would|can|should|need to)|let me|next[, ]|now\s+i|"
    r"i'?ll\s+(?:call|use|check|inspect|build|create)|"
    r"the next step is)\b",
    re.IGNORECASE,
)


@dataclass(kw_only=True)
class FollowupGuardInputs:
    """Inputs of ``handle_followup_response_guards``; the counters are updated while the guards run."""

    db: Any
    session_id: str
    runtime: dict[str, Any]
    response: dict[str, Any]
    request_messages: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    runtime_settings: dict[str, Any]
    usage_model: str
    content: str
    tool_calls: list[dict[str, Any]] | None
    current_step: dict[str, Any] | None
    current_turn_content: str
    request_analysis: dict[str, Any]
    context_plan: Any
    turn_tool_history: list[dict[str, Any]]
    step_tool_history: list[dict[str, Any]]
    executed_tool_names: set[str]
    covered_evidence_axes: set[str]
    workflow_contract: dict[str, Any] | None
    workflow_id: str
    tdd_cycle_state: dict[str, Any] | None
    consecutive_non_progress_response_count: int
    consecutive_coding_no_execution_count: int
    consecutive_transitional_response_count: int
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    build_stalled_step_message: Callable[[dict[str, Any] | None], str]
    build_tdd_cycle_incomplete_reminder: Callable[[dict[str, Any], dict[str, Any]], str]
    build_initial_tdd_cycle_state: Callable[[], dict[str, Any]]
    is_tdd_cycle_complete: _StepCheck
    is_tdd_cycle_step: _StepCheck
    _is_self_review_step: _StepCheck
    _is_self_review_step_complete: Callable[[dict[str, Any] | None, list[dict[str, Any]]], bool]
    _build_incomplete_self_review_reminder: Callable[[dict[str, Any]], str]
    workflow_artifact_contract_satisfied: Callable[..., bool]


def _usable_model_draft(content: str) -> str:
    text = str(content or "").strip()
    if len(text) < 80:
        return ""
    if _NON_SUBSTANTIVE_DRAFT_PATTERN.search(text):
        return ""
    return text


def _followup_guard_final_content(
    *,
    content: str,
    current_step: dict[str, Any] | None,
    build_stalled_step_message: Callable[[dict[str, Any] | None], str],
) -> str:
    model_draft = _usable_model_draft(content)
    if model_draft:
        return model_draft

    step_message = str(build_stalled_step_message(current_step) if current_step else "").strip()
    if step_message and "agent stopped because" not in step_message.lower():
        return step_message

    return render_prompt("loop.followup.no_tool_stop")


def followup_result(run: FollowupGuardInputs, action: str, **extra: Any) -> dict[str, Any]:
    """Action dict carrying the three loop counters; ``extra`` adds keys such as the yielded content."""
    return {
        "action": action,
        **extra,
        "consecutive_non_progress_response_count": run.consecutive_non_progress_response_count,
        "consecutive_coding_no_execution_count": run.consecutive_coding_no_execution_count,
        "consecutive_transitional_response_count": run.consecutive_transitional_response_count,
    }


def _followup_no_tool_limit(run: FollowupGuardInputs) -> int:
    default_limit = max(
        2,
        int(run.runtime_settings.get("stuck_loop_no_tool_duplicate_threshold") or 2),
    )
    current_step = run.current_step
    if not isinstance(current_step, dict):
        return default_limit
    step_config = current_step.get("stepConfig")
    if not isinstance(step_config, dict):
        step_config = current_step.get("step_config")
    if not isinstance(step_config, dict):
        return default_limit
    try:
        explicit_limit = int(step_config.get("max_followup_no_tool_responses"))
    except (TypeError, ValueError):
        explicit_limit = 0
    if explicit_limit <= 0:
        return default_limit
    return max(1, min(explicit_limit, 32))


async def remind_and_continue_or_stop(
    run: FollowupGuardInputs, *, reminder: str, raw_output: dict[str, Any]
) -> dict[str, Any]:
    """Append the reminder, persist the suppressed reply, and continue until the no-tool limit stops the turn."""
    run.messages.append({"role": "assistant", "content": run.content or ""})
    run.messages.append({"role": "system", "content": reminder})
    run.consecutive_non_progress_response_count += 1
    await run.persist_suppressed_runtime_response(
        db=run.db,
        session_id=run.session_id,
        provider=run.runtime["provider_name"],
        model=run.usage_model,
        request_messages=run.request_messages,
        context_snapshot=run.context_snapshot,
        response=run.response,
        raw_output=raw_output,
        trace_limits=run.runtime_settings,
    )
    if run.consecutive_non_progress_response_count < _followup_no_tool_limit(run):
        return followup_result(run, "continue")

    final_content = _followup_guard_final_content(
        content=str(raw_output.get("content") or run.content or ""),
        current_step=run.current_step,
        build_stalled_step_message=run.build_stalled_step_message,
    )
    await run.persist_traced_assistant_message(
        db=run.db,
        session_id=run.session_id,
        content=final_content,
        provider=run.runtime["provider_name"],
        model=run.usage_model,
        input_messages=run.request_messages,
        context_snapshot=run.context_snapshot,
        tool_trace=[],
        raw_output={
            **raw_output,
            "stalled_on_followup_no_tool_loop": True,
            "non_progress_loop_count": run.consecutive_non_progress_response_count,
        },
        usage=run.response.get("usage", {}),
        tokens_in=run.response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=run.response.get("usage", {}).get("completion_tokens", 0),
        trace_limits=run.runtime_settings,
    )
    return followup_result(run, "return", yield_content=final_content, yield_model=run.usage_model)
