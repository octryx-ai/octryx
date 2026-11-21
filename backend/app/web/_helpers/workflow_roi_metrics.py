"""Per-session usage and quality metrics loaded for the workflow ROI comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ToolCall, TurnTrace, UsageEvent, WorkflowCheckResult


@dataclass(frozen=True)
class SessionUsageMetrics:
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    llm_request_count: int = 0
    tool_call_count: int = 0
    turn_trace_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def deterministic_step_count(self) -> int:
        deterministic_steps = max(self.turn_trace_count - self.llm_request_count, 0)
        if deterministic_steps == 0 and self.llm_request_count == 0 and self.tool_call_count:
            return self.tool_call_count
        return deterministic_steps


async def _load_metrics_by_session_id(
    db: AsyncSession,
    session_ids: list[str],
) -> dict[str, SessionUsageMetrics]:
    if not session_ids:
        return {}

    usage_rows = (
        await db.execute(
            select(
                UsageEvent.session_id,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost), 0),
            )
            .where(UsageEvent.session_id.in_(session_ids))
            .group_by(UsageEvent.session_id)
        )
    ).all()
    tool_rows = (
        await db.execute(
            select(ToolCall.session_id, func.count(ToolCall.id))
            .where(ToolCall.session_id.in_(session_ids))
            .group_by(ToolCall.session_id)
        )
    ).all()
    trace_rows = (
        await db.execute(
            select(TurnTrace.session_id, func.count(TurnTrace.id))
            .where(TurnTrace.session_id.in_(session_ids))
            .group_by(TurnTrace.session_id)
        )
    ).all()
    rows: dict[str, dict[str, Any]] = {session_id: {} for session_id in session_ids}
    for session_id, request_count, tokens_in, tokens_out, cost in usage_rows:
        rows[str(session_id)].update(
            {
                "llm_request_count": int(request_count or 0),
                "input_tokens": int(tokens_in or 0),
                "output_tokens": int(tokens_out or 0),
                "total_cost": float(cost or 0),
            }
        )
    for session_id, tool_count in tool_rows:
        rows[str(session_id)]["tool_call_count"] = int(tool_count or 0)
    for session_id, trace_count in trace_rows:
        rows[str(session_id)]["turn_trace_count"] = int(trace_count or 0)
    return {
        session_id: SessionUsageMetrics(
            input_tokens=int(values.get("input_tokens") or 0),
            output_tokens=int(values.get("output_tokens") or 0),
            total_cost=float(values.get("total_cost") or 0),
            llm_request_count=int(values.get("llm_request_count") or 0),
            tool_call_count=int(values.get("tool_call_count") or 0),
            turn_trace_count=int(values.get("turn_trace_count") or 0),
        )
        for session_id, values in rows.items()
    }


async def _load_quality_summary(
    db: AsyncSession,
    *,
    current_session_ids: list[str],
    baseline_session_ids: list[str],
) -> dict[str, Any]:
    # The sessions already share one workflow identity; their check results are the quality signal.
    session_ids = [*current_session_ids, *baseline_session_ids]
    if not session_ids:
        return {"status": "not_measured", "current": {}, "baseline": {}}
    stmt = select(WorkflowCheckResult).where(WorkflowCheckResult.session_id.in_(session_ids))
    rows = (await db.execute(stmt.order_by(WorkflowCheckResult.created_at.desc()))).scalars().all()
    current = _quality_bucket(rows, set(current_session_ids))
    baseline = _quality_bucket(rows, set(baseline_session_ids))
    status = "measured" if current["run_count"] or baseline["run_count"] else "not_measured"
    return {"status": status, "current": current, "baseline": baseline}


def _quality_bucket(rows: list[WorkflowCheckResult], session_ids: set[str]) -> dict[str, Any]:
    matching = [row for row in rows if row.session_id in session_ids]
    passed = sum(1 for row in matching if row.state == "passed")
    failed = len(matching) - passed
    return {
        "run_count": len(matching),
        "passed_count": passed,
        "failed_count": failed,
        "pass_rate": (passed / len(matching)) if matching else 0.0,
    }
