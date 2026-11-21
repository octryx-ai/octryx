"""Shared environment, persistence helpers and the AWS report / sub-agent phases of ``handle_post_tool_outcome``.

Each phase mirrors one sequential decision block of the post-tool outcome
handler and returns an action dict when it terminates the turn, or ``None``
to fall through to the next phase. Artifact and report phases live in
``_loop_post_tool_reports``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..control._loop_salvage_hooks import render_evidence_salvage_message
from ._loop_post_tool_history import (
    _read_only_child_wrapup_content,
    _should_finish_read_only_child,
)


@dataclass(frozen=True)
class _PostToolEnv:
    """Shared read-only inputs threaded through the post-tool phases."""

    db: Any
    session_id: str
    runtime: dict[str, Any]
    response: dict[str, Any]
    request_messages: list[dict[str, Any]]
    context_snapshot: dict[str, Any]
    tool_results: list[dict[str, Any]]
    current_user_message: str
    content: str
    usage_model: str
    runtime_settings: dict[str, Any]
    runtime_attempts: list[dict[str, Any]]
    request_analysis: dict[str, Any]
    turn_tool_history: list[dict[str, Any]]
    workflow_contract: Any
    post_tool_history: list[dict[str, Any]]
    persist_synthesized_tool_assistant: Callable[..., Any]
    persist_traced_assistant_message: Callable[..., Any]
    fetch_thread_context_state: Callable[..., Any]


async def _persist_synthesized_and_return(
    env: _PostToolEnv,
    *,
    synthesized_content: str,
    source: str,
    tool_results: list[dict[str, Any]] | None = None,
    context_snapshot: dict[str, Any] | None = None,
    assistant_content: str | None = None,
    workflow_decision_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a synthesized assistant message and build the terminal action dict."""
    # Only a capability escalation passes a decision request; other callers keep the
    # persistence call unchanged.
    decision_kwargs = {"workflow_decision_request": workflow_decision_request} if workflow_decision_request else {}
    await env.persist_synthesized_tool_assistant(
        db=env.db,
        session_id=env.session_id,
        runtime=env.runtime,
        response=env.response,
        request_messages=env.request_messages,
        context_snapshot=env.context_snapshot if context_snapshot is None else context_snapshot,
        tool_results=env.tool_results if tool_results is None else tool_results,
        current_user_message=env.current_user_message,
        content=synthesized_content,
        source=source,
        assistant_content=env.content if assistant_content is None else assistant_content,
        trace_limits=env.runtime_settings,
        **decision_kwargs,
    )
    existing_thread_context = await env.fetch_thread_context_state(env.db, env.session_id)
    return {
        "action": "return",
        "existing_thread_context": existing_thread_context,
        "yield_content": synthesized_content,
        "yield_model": f"{env.runtime['provider_name']}/{env.usage_model}",
    }


async def _persist_stop_run_and_return(
    env: _PostToolEnv,
    *,
    final_content: str,
    raw_output: dict[str, Any],
) -> dict[str, Any]:
    """Persist a traced stop-run assistant message and build the terminal action dict."""
    await env.persist_traced_assistant_message(
        db=env.db,
        session_id=env.session_id,
        content=final_content,
        provider=env.runtime["provider_name"],
        model=env.usage_model,
        input_messages=env.request_messages,
        context_snapshot=env.context_snapshot,
        tool_trace=env.tool_results,
        raw_output=raw_output,
        usage=env.response.get("usage", {}),
        tokens_in=env.response.get("usage", {}).get("prompt_tokens", 0),
        tokens_out=env.response.get("usage", {}).get("completion_tokens", 0),
        trace_limits=env.runtime_settings,
    )
    return {"action": "return", "yield_content": final_content, "yield_model": env.usage_model}


async def _aws_evidence_report_outcome(env: _PostToolEnv, *, source: str) -> dict[str, Any] | None:
    evidence_budget_report = render_evidence_salvage_message(
        user_request=env.current_user_message,
        recent_tool_calls=env.post_tool_history,
    )
    if not evidence_budget_report:
        return None
    return await _persist_synthesized_and_return(env, synthesized_content=evidence_budget_report, source=source)


async def _read_only_child_outcome(
    env: _PostToolEnv, *, current_allowed_tool_names: set[str]
) -> dict[str, Any] | None:
    if not _should_finish_read_only_child(
        context_snapshot=env.context_snapshot,
        current_allowed_tool_names=current_allowed_tool_names,
        history=env.post_tool_history,
    ):
        return None
    synthesized_content = _read_only_child_wrapup_content(
        current_user_message=env.current_user_message,
        history=env.post_tool_history,
    )
    return await _persist_synthesized_and_return(
        env, synthesized_content=synthesized_content, source="read_only_sub_agent_evidence_budget"
    )
