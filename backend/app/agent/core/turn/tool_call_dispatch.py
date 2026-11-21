"""Decide a tool call's result: a refusal, a guard result, a cached answer or a real execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_tool_surface_decision import tool_surface_dispatch_refusal
from app.tools.context import ToolContext

from ....services.context_checkpoint import get_active_context_checkpoint
from ....services.prefetch import lookup_prefetch_cache
from ....services.prompt_catalog import render_prompt
from ....services.session.tool_cache import lookup_session_tool_cache, store_session_tool_cache
from ....services.tool_planning import enforce_tool_execution_control
from ....services.turn_tool_guards import (
    is_required_summary_domain_tool as _is_required_summary_domain_tool,
)
from .tool_call_dedup import duplicate_read_only_tool_result
from .tool_call_guards import alert_scoped, tool_execution_guard_result


@dataclass(kw_only=True)
class ToolDispatchRequest:
    """The inputs of ``dispatch_tool_call``; the caller builds it once per tool call."""

    db: AsyncSession
    tool_context: ToolContext
    tool_name: str
    tool_args: dict[str, Any]
    context_snapshot: dict[str, Any]
    turn_tool_history: list[dict[str, Any]] | None
    configured_step_allowed_tool_names: set[str]
    exec_policy_config: dict[str, Any]
    execute_tool: Callable[[str, dict[str, Any], ToolContext], Any]


@dataclass(kw_only=True)
class ToolDispatchOutcome:
    result: dict[str, Any]
    cache_meta: dict[str, Any] | None = None
    cache_hit_kind: str | None = None


def _duplicate_skip(duplicate_read_only_result: dict[str, Any]) -> ToolDispatchOutcome:
    return ToolDispatchOutcome(
        result=duplicate_read_only_result, cache_meta={"status": "turn_duplicate_skip"}, cache_hit_kind="turn_duplicate"
    )


async def _cached_or_executed(request: ToolDispatchRequest) -> ToolDispatchOutcome:
    db, tool_context = request.db, request.tool_context
    tool_name, tool_args = request.tool_name, request.tool_args
    # A run with an alert scope never reuses a cached answer, which skipped the scope check.
    scoped = await alert_scoped(tool_context)
    prefetched = None if scoped else await lookup_prefetch_cache(
        db,
        session_id=tool_context.session_id,
        tool_name=tool_name,
        params=tool_args,
    )
    if prefetched is not None:
        result, prefetch_meta = prefetched
        return ToolDispatchOutcome(
            result=result, cache_meta={"status": "prefetch_hit", **prefetch_meta}, cache_hit_kind="prefetch"
        )
    cached = None if scoped else await lookup_session_tool_cache(
        db,
        session_id=tool_context.session_id,
        tool_name=tool_name,
        params=tool_args,
    )
    if cached is not None:
        result, session_cache_meta = cached
        return ToolDispatchOutcome(
            result=result, cache_meta={"status": "hit", **session_cache_meta}, cache_hit_kind="session"
        )
    result = await request.execute_tool(tool_name, tool_args, tool_context)
    if not scoped:
        await store_session_tool_cache(
            db,
            session_id=tool_context.session_id,
            tool_name=tool_name,
            params=tool_args,
            result=result,
        )
    return ToolDispatchOutcome(result=result)


async def _guarded_dispatch(
    request: ToolDispatchRequest, duplicate_read_only_result: dict[str, Any] | None
) -> ToolDispatchOutcome:
    guard_result = tool_execution_guard_result(
        tool_name=request.tool_name,
        tool_args=request.tool_args,
        turn_tool_history=request.turn_tool_history,
        capability_type=request.tool_context.capability_type,
        context_snapshot=request.context_snapshot,
        exec_policy_config=request.exec_policy_config,
    )
    if guard_result is not None:
        return ToolDispatchOutcome(result=guard_result)
    if duplicate_read_only_result is not None:
        return _duplicate_skip(duplicate_read_only_result)
    return await _cached_or_executed(request)


def _step_refusal(tool_name: str, configured_step_allowed_tool_names: set[str]) -> dict[str, Any]:
    return {
        "error": (
            f"Tool '{tool_name}' is not allowed in the current step. "
            f"Allowed tools: {', '.join(sorted(configured_step_allowed_tool_names))}"
        )
    }


async def dispatch_tool_call(request: ToolDispatchRequest) -> ToolDispatchOutcome:
    """Run the checks in fixed order; the first that answers decides, and only a call that passes all executes."""
    tool_name, tool_context = request.tool_name, request.tool_context
    active_checkpoint = await get_active_context_checkpoint(request.db, session_id=tool_context.session_id)
    meta_tool_override = tool_name in {"release_context", "load_tool_artifact"}
    execution_control_result = enforce_tool_execution_control(
        tool_name=tool_name,
        context_snapshot=request.context_snapshot,
        turn_tool_history=request.turn_tool_history,
        current_allowed_tool_names=request.configured_step_allowed_tool_names,
    )
    duplicate_read_only_result = duplicate_read_only_tool_result(
        tool_name=tool_name,
        tool_args=request.tool_args,
        turn_tool_history=request.turn_tool_history,
    )
    # Before any cache: a text-only agent gets no tool result, not even a cached one.
    surface_refusal = tool_surface_dispatch_refusal(tool_name, tool_context)
    if surface_refusal is not None:
        return ToolDispatchOutcome(result=surface_refusal)
    if active_checkpoint is not None and not meta_tool_override:
        return ToolDispatchOutcome(
            result={
                "error": render_prompt(
                    "tool_guard.turn.checkpoint_frozen", checkpoint_name=active_checkpoint.checkpoint_name
                ),
                "checkpoint_name": active_checkpoint.checkpoint_name,
                "checkpoint_status": active_checkpoint.status,
            }
        )
    if execution_control_result is not None:
        return ToolDispatchOutcome(result=execution_control_result)
    if duplicate_read_only_result is not None:
        return _duplicate_skip(duplicate_read_only_result)
    allowed = request.configured_step_allowed_tool_names
    if allowed and tool_name not in allowed and not meta_tool_override:
        if not _is_required_summary_domain_tool(tool_name=tool_name, context_snapshot=request.context_snapshot):
            return ToolDispatchOutcome(result=_step_refusal(tool_name, allowed))
    return await _guarded_dispatch(request, duplicate_read_only_result)
