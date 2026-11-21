"""Usage, cost and activity totals of a thread (a session and its sub-sessions) for the chat stats panel."""

from __future__ import annotations

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Message, ToolCall, TurnTrace, UsageEvent
from .trace_usage_stats import load_trace_usage_stats
from .workflow_roi_stats import build_workflow_roi_stats

__all__ = ["_load_thread_usage_stats"]


def _empty_thread_usage_stats() -> dict:
    return {
        "context_tokens": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "non_cached_input_tokens": 0,
        "total_cost": 0.0,
        "cost_by_model": [],
        "request_count": 0,
        "llm_request_count": 0,
        "tool_call_count": 0,
        "turn_trace_count": 0,
        "deterministic_step_count": 0,
        "zero_cost_reason": "",
        "workflow_roi": None,
        "message_count": 0,
        "user_message_count": 0,
        "assistant_message_count": 0,
        "last_model": "",
        "last_provider": "",
    }


async def _usage_event_facts(db: AsyncSession, session_ids: list[str]) -> tuple[Any, list[Any], UsageEvent | None]:
    """Usage event totals, the per-model breakdown (costliest first) and the newest usage event."""
    usage_row = (
        await db.execute(
            select(
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost), 0),
            ).where(UsageEvent.session_id.in_(session_ids))
        )
    ).one()
    model_cost_sum = func.coalesce(func.sum(UsageEvent.cost), 0)
    model_usage_rows = (
        await db.execute(
            select(
                UsageEvent.provider,
                UsageEvent.model,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                model_cost_sum.label("cost"),
            )
            .where(UsageEvent.session_id.in_(session_ids))
            .group_by(UsageEvent.provider, UsageEvent.model)
            .order_by(model_cost_sum.desc(), func.count(UsageEvent.id).desc())
        )
    ).all()
    latest_usage = (
        await db.execute(
            select(UsageEvent)
            .where(UsageEvent.session_id.in_(session_ids))
            .order_by(UsageEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return usage_row, model_usage_rows, latest_usage


async def _count_for_sessions(db: AsyncSession, model: Any, session_ids: list[str]) -> int:
    count_query = select(func.count(model.id)).where(model.session_id.in_(session_ids))
    return int((await db.execute(count_query)).scalar_one() or 0)


async def _message_counts(db: AsyncSession, session_ids: list[str]) -> Any:
    """Messages, user messages and assistant messages."""
    return (
        await db.execute(
            select(
                func.count(Message.id),
                func.coalesce(func.sum(case((Message.role == "user", 1), else_=0)), 0),
                func.coalesce(func.sum(case((Message.role == "assistant", 1), else_=0)), 0),
            ).where(Message.session_id.in_(session_ids))
        )
    ).one()


def _zero_cost_reason(usage_request_count: int, tool_activity: int) -> str:
    if usage_request_count == 0 and tool_activity:
        return "No LLM usage events were recorded; this thread contains deterministic tool or workflow activity."
    return ""


def _cost_by_model(model_usage_rows: list[Any]) -> list[dict]:
    return [
        {
            "provider": provider or "",
            "model": model or "",
            "request_count": int(request_count or 0),
            "input_tokens": int(tokens_in or 0),
            "output_tokens": int(tokens_out or 0),
            "cost": float(cost or 0),
        }
        for provider, model, request_count, tokens_in, tokens_out, cost in model_usage_rows
    ]


async def _load_thread_usage_stats(
    db: AsyncSession,
    *,
    session_ids: list[str],
) -> dict:
    if not session_ids:
        return _empty_thread_usage_stats()

    usage_row, model_usage_rows, latest_usage = await _usage_event_facts(db, session_ids)
    tool_call_count = await _count_for_sessions(db, ToolCall, session_ids)
    turn_trace_count = await _count_for_sessions(db, TurnTrace, session_ids)
    message_counts_row = await _message_counts(db, session_ids)

    usage_request_count = int(usage_row[0] or 0)
    trace_usage_stats = await load_trace_usage_stats(db, session_ids=session_ids)
    effective_request_count = usage_request_count or int(trace_usage_stats.get("request_count") or 0)
    effective_tokens_in = int(usage_row[1] or 0) or int(trace_usage_stats.get("input_tokens") or 0)
    effective_tokens_out = int(usage_row[2] or 0) or int(trace_usage_stats.get("output_tokens") or 0)
    deterministic_step_count = max(turn_trace_count - effective_request_count, 0)
    if deterministic_step_count == 0 and usage_request_count == 0 and tool_call_count:
        deterministic_step_count = tool_call_count

    stats = {
        "context_tokens": effective_tokens_in + effective_tokens_out,
        "input_tokens": effective_tokens_in,
        "output_tokens": effective_tokens_out,
        "cache_read_input_tokens": trace_usage_stats["cache_read_input_tokens"],
        "cache_write_input_tokens": trace_usage_stats["cache_write_input_tokens"],
        "non_cached_input_tokens": trace_usage_stats["non_cached_input_tokens"],
        "total_cost": float(usage_row[3] or 0),
        "cost_by_model": _cost_by_model(model_usage_rows),
        "request_count": effective_request_count,
        "llm_request_count": effective_request_count,
        "tool_call_count": tool_call_count,
        "turn_trace_count": turn_trace_count,
        "deterministic_step_count": deterministic_step_count,
        "zero_cost_reason": _zero_cost_reason(usage_request_count, tool_call_count or deterministic_step_count),
        "message_count": int(message_counts_row[0] or 0),
        "user_message_count": int(message_counts_row[1] or 0),
        "assistant_message_count": int(message_counts_row[2] or 0),
        "last_model": latest_usage.model if latest_usage else "",
        "last_provider": latest_usage.provider if latest_usage else "",
    }
    stats["workflow_roi"] = await build_workflow_roi_stats(
        db,
        session_ids=session_ids,
        current_metrics=stats,
    )
    return stats
