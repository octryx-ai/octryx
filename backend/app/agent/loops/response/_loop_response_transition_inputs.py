"""Inputs and shared helpers of ``handle_transition_response_guards``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ...core.guards.response_guards import get_step_field


@dataclass(kw_only=True)
class TransitionGuardInputs:
    """Inputs of ``handle_transition_response_guards``; the counters are updated while the guards run."""

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
    current_tool_definitions: list[dict[str, Any]]
    current_step: dict[str, Any] | None
    has_followup_steps: bool
    turn_tool_history: list[dict[str, Any]]
    consecutive_non_progress_response_count: int
    consecutive_transitional_response_count: int
    is_transitional_assistant_response: Callable[[str, list[dict[str, Any]] | None, bool], bool]
    is_non_substantive_assistant_response: Callable[..., bool]
    looks_like_step_completion_summary: Callable[[str], bool]
    build_stalled_step_message: Callable[[dict[str, Any]], str]
    persist_suppressed_runtime_response: Callable[..., Any]
    persist_turn_trace: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    workflow_id: str
    request_analysis: dict[str, Any] | None = None
    # The latest user message of the request; derived, never passed by callers.
    latest_user_message: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.latest_user_message = next(
            (
                str(message.get("content") or "")
                for message in reversed(self.request_messages)
                if str(message.get("role") or "").strip() == "user"
            ),
            "",
        )


def transition_loop_limit(run: TransitionGuardInputs) -> int:
    default_limit = max(
        2,
        int(run.runtime_settings.get("stuck_loop_no_tool_duplicate_threshold") or 2),
    )
    step_config = get_step_field(run.current_step, "stepConfig", "step_config", None)
    if not isinstance(step_config, dict):
        return default_limit
    try:
        explicit_limit = int(step_config.get("max_transitional_responses"))
    except (TypeError, ValueError):
        explicit_limit = 0
    if explicit_limit <= 0:
        return default_limit
    return max(1, min(explicit_limit, 32))


def transition_result(run: TransitionGuardInputs, action: str, **extra: Any) -> dict[str, Any]:
    """Action dict carrying both loop counters; ``extra`` adds keys such as the yielded content."""
    return {
        "action": action,
        **extra,
        "consecutive_non_progress_response_count": run.consecutive_non_progress_response_count,
        "consecutive_transitional_response_count": run.consecutive_transitional_response_count,
    }


async def persist_stop_message(run: TransitionGuardInputs, *, final_content: str, raw_output: dict[str, Any]) -> None:
    await run.persist_traced_assistant_message(
        db=run.db,
        session_id=run.session_id,
        content=final_content,
        provider=run.runtime["provider_name"],
        model=run.usage_model,
        input_messages=run.request_messages,
        context_snapshot=run.context_snapshot,
        tool_trace=[],
        raw_output=raw_output,
        usage=run.response.get("usage", {}),
        tokens_in=run.response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=run.response.get("usage", {}).get("completion_tokens", 0),
        trace_limits=run.runtime_settings,
    )


async def persist_suppressed_trace(run: TransitionGuardInputs, *, raw_output: dict[str, Any]) -> None:
    await run.persist_turn_trace(
        db=run.db,
        session_id=run.session_id,
        message_id=None,
        provider=run.runtime["provider_name"],
        model=run.usage_model,
        input_messages=run.request_messages,
        context_snapshot=run.context_snapshot,
        tool_trace=[],
        raw_output=raw_output,
        usage=run.response.get("usage", {}),
        trace_limits=run.runtime_settings,
    )
