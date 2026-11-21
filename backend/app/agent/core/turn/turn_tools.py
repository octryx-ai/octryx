"""Helpers for per-turn tool execution inside the agent loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.context import ToolContext

from ....services.request_context import get_current_request_id
from ....services.session.runtime_events import publish_tool_call_begin
from ....services.tool_artifact import build_tool_artifact_envelope, serialize_tool_artifact_envelope
from ....services.tool_artifact.summary import result_was_shortened
from ....services.turn_tool_guards import (
    sanitize_tool_name as _sanitize_tool_name,
)
from ....time_utils import utc_now
from ....tools.argument_sanitizers import publishable_tool_arguments
from .tool_call_dispatch import ToolDispatchOutcome, ToolDispatchRequest, dispatch_tool_call
from .tool_call_guards import load_and_audit_custom_tool_guards
from .tool_call_recording import ToolCallRecord, apply_repository_tool_effects, record_tool_call
from .tool_call_rewrites import enforce_evidence_bound_tool_call, parse_tool_call_arguments, prepare_tool_arguments
from .tool_call_step import ToolCallStep, resolve_tool_call_step
from .turn_diff import TurnDiffTracker


@dataclass
class ExecutedToolCall:
    tool_result: dict[str, Any]
    message_for_model: dict[str, Any]
    tool_args: dict[str, Any]
    current_step_index: int
    current_step_tool_activity: bool
    current_allowed_tool_names: set[str]
    latest_repo_state: dict[str, str]
    covered_domains: set[str]


def _message_for_model(
    tool_call_id: str, artifact_id: str, tool_name: str, result: dict[str, Any], compact_result: dict[str, Any]
) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": serialize_tool_artifact_envelope(
            build_tool_artifact_envelope(
                artifact_id=artifact_id,
                tool_name=tool_name,
                payload=compact_result,
                include_result=True,
                shortened=result_was_shortened(result, compact_result),
            )
        ),
    }


@dataclass(kw_only=True)
class _TurnToolCall:
    """The inputs of one ``execute_tool_call_for_turn`` call, handed to its phases."""

    db: AsyncSession
    assistant_message_id: str
    tool_call: dict[str, Any]
    tool_context: ToolContext
    active_steps: list[dict[str, Any]]
    current_step_index: int
    current_step_tool_activity: bool
    current_allowed_tool_names: set[str]
    latest_repo_state: dict[str, str]
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]]
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]]
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]]
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None], set[str]]
    execute_tool: Callable[[str, dict[str, Any], ToolContext], Any]
    turn_diff_tracker: TurnDiffTracker
    context_snapshot: dict[str, Any]
    turn_tool_history: list[dict[str, Any]] | None


def _prepared_call(call: _TurnToolCall) -> tuple[str, str, dict[str, Any]]:
    """The call id, the final tool name and the arguments the tool is dispatched with."""
    tc_id = call.tool_call.get("id", "")
    func = call.tool_call.get("function", {})
    tool_name = _sanitize_tool_name(
        func.get("name", ""),
        allowed_tool_names=call.current_allowed_tool_names,
        capability_type=call.tool_context.capability_type,
    )
    if isinstance(func, dict):
        func["name"] = tool_name
    tool_name, tool_args = enforce_evidence_bound_tool_call(
        func=func,
        tool_name=tool_name,
        tool_args=parse_tool_call_arguments(func.get("arguments", "{}")),
        turn_tool_history=call.turn_tool_history,
        allowed_tool_names=call.current_allowed_tool_names,
        context_snapshot=call.context_snapshot,
    )
    tool_args = prepare_tool_arguments(
        tool_name=tool_name,
        tool_args=tool_args,
        tool_context=call.tool_context,
        latest_repo_state=call.latest_repo_state,
        infer_repo_tool_args=call.infer_repo_tool_args,
        context_snapshot=call.context_snapshot,
        turn_tool_history=call.turn_tool_history,
    )
    return tc_id, tool_name, tool_args


async def _announce_call(
    call: _TurnToolCall, *, tc_id: str, tool_name: str, tool_args: dict[str, Any], persistable_tool_args: dict[str, Any]
) -> tuple[dict[str, Any], str | None, datetime]:
    """Audit the custom guards and publish the begin event; returns the exec policy, request id and start time."""
    tool_context = call.tool_context
    exec_policy_config = await load_and_audit_custom_tool_guards(
        call.db,
        tool_context=tool_context,
        assistant_message_id=call.assistant_message_id,
        tool_call_id=tc_id,
        tool_name=tool_name,
        tool_args=tool_args,
        persistable_tool_args=persistable_tool_args,
        context_snapshot=call.context_snapshot,
    )

    start_time = utc_now()
    request_id = tool_context.request_id or get_current_request_id()
    await publish_tool_call_begin(
        session_id=tool_context.session_id,
        turn_id=request_id,
        tool_call_id=tc_id,
        tool_name=tool_name,
        parameters=persistable_tool_args,
        request_id=request_id,
    )
    return exec_policy_config, request_id, start_time


async def _execute(call: _TurnToolCall) -> ExecutedToolCall:
    tc_id, tool_name, tool_args = _prepared_call(call)
    # Everything that records this call outside dispatch — the guard audit, the
    # runtime event stream, the ``ToolCall`` row, the turn diff, and the history
    # the next prompt is built from — keeps the publishable projection, never the
    # raw arguments. They are all written before governance has decided anything,
    # so a credential-bearing argument must not be what they keep.
    persistable_tool_args = publishable_tool_arguments(tool_name, tool_args)
    exec_policy_config, request_id, start_time = await _announce_call(
        call, tc_id=tc_id, tool_name=tool_name, tool_args=tool_args, persistable_tool_args=persistable_tool_args
    )
    step = await resolve_tool_call_step(
        call.db,
        tool_context=call.tool_context,
        tool_name=tool_name,
        active_steps=call.active_steps,
        current_step_index=call.current_step_index,
        current_step_tool_activity=call.current_step_tool_activity,
        current_allowed_tool_names=call.current_allowed_tool_names,
        resolve_allowed_tools_for_step_tool_call=call.resolve_allowed_tools_for_step_tool_call,
    )
    dispatched = await dispatch_tool_call(
        ToolDispatchRequest(
            db=call.db,
            tool_context=call.tool_context,
            tool_name=tool_name,
            tool_args=tool_args,
            context_snapshot=call.context_snapshot,
            turn_tool_history=call.turn_tool_history,
            configured_step_allowed_tool_names=step.configured_step_allowed_tool_names,
            exec_policy_config=exec_policy_config,
            execute_tool=call.execute_tool,
        )
    )
    duration_ms = 0 if dispatched.cache_meta else int((utc_now() - start_time).total_seconds() * 1000)
    return await _finish(
        call,
        tc_id=tc_id,
        request_id=request_id,
        tool_name=tool_name,
        tool_args=tool_args,
        persistable_tool_args=persistable_tool_args,
        step=step,
        dispatched=dispatched,
        duration_ms=duration_ms,
    )


async def _finish(
    call: _TurnToolCall,
    *,
    tc_id: str,
    request_id: str | None,
    tool_name: str,
    tool_args: dict[str, Any],
    persistable_tool_args: dict[str, Any],
    step: ToolCallStep,
    dispatched: ToolDispatchOutcome,
    duration_ms: int,
) -> ExecutedToolCall:
    result, latest_repo_state = await apply_repository_tool_effects(
        call.db,
        tool_context=call.tool_context,
        tool_name=tool_name,
        tool_args=tool_args,
        result=dispatched.result,
        latest_repo_state=call.latest_repo_state,
    )
    tool_result, artifact_id, compact_result = await record_tool_call(
        ToolCallRecord(
            db=call.db,
            tool_context=call.tool_context,
            assistant_message_id=call.assistant_message_id,
            tool_call_id=tc_id,
            request_id=request_id,
            tool_name=tool_name,
            persistable_tool_args=persistable_tool_args,
            result=result,
            cache_meta=dispatched.cache_meta,
            cache_hit_kind=dispatched.cache_hit_kind,
            duration_ms=duration_ms,
            compact_tool_result_for_model=call.compact_tool_result_for_model,
            turn_diff_tracker=call.turn_diff_tracker,
            context_snapshot=call.context_snapshot,
        )
    )
    return ExecutedToolCall(
        tool_result=tool_result,
        message_for_model=_message_for_model(tc_id, artifact_id, tool_name, result, compact_result),
        tool_args=dict(persistable_tool_args or {}),
        current_step_index=step.current_step_index,
        current_step_tool_activity=True,
        current_allowed_tool_names=step.current_allowed_tool_names,
        latest_repo_state=latest_repo_state,
        covered_domains=call.summary_domains_satisfied_by_result(tool_name, result),
    )


async def execute_tool_call_for_turn(
    *,
    db: AsyncSession,
    assistant_message_id: str,
    tool_call: dict[str, Any],
    tool_context: ToolContext,
    active_steps: list[dict[str, Any]],
    current_step_index: int,
    current_step_tool_activity: bool,
    current_allowed_tool_names: set[str],
    latest_repo_state: dict[str, str],
    infer_repo_tool_args: Callable[[str, dict[str, Any], dict[str, str]], dict[str, Any]],
    resolve_allowed_tools_for_step_tool_call: Callable[..., tuple[int, bool, set[str]]],
    compact_tool_result_for_model: Callable[[str, dict[str, Any]], dict[str, Any]],
    summary_domains_satisfied_by_result: Callable[[str, dict[str, Any] | None], set[str]],
    execute_tool: Callable[[str, dict[str, Any], ToolContext], Any],
    turn_diff_tracker: TurnDiffTracker,
    context_snapshot: dict[str, Any],
    turn_tool_history: list[dict[str, Any]] | None = None,
) -> ExecutedToolCall:
    return await _execute(
        _TurnToolCall(
            db=db,
            assistant_message_id=assistant_message_id,
            tool_call=tool_call,
            tool_context=tool_context,
            active_steps=active_steps,
            current_step_index=current_step_index,
            current_step_tool_activity=current_step_tool_activity,
            current_allowed_tool_names=current_allowed_tool_names,
            latest_repo_state=latest_repo_state,
            infer_repo_tool_args=infer_repo_tool_args,
            resolve_allowed_tools_for_step_tool_call=resolve_allowed_tools_for_step_tool_call,
            compact_tool_result_for_model=compact_tool_result_for_model,
            summary_domains_satisfied_by_result=summary_domains_satisfied_by_result,
            execute_tool=execute_tool,
            turn_diff_tracker=turn_diff_tracker,
            context_snapshot=context_snapshot,
            turn_tool_history=turn_tool_history,
        )
    )
