"""Loop limits, run budgets and the paused state."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import UsageEvent, WorkflowRun, WorkflowRunSession
from ...models.runtime.secure_work import WorkItem
from ...time_utils import ensure_utc, utc_now
from ..system_config.values import get_system_config_value, set_system_config_value
from .graph import PhasedEdge, PhasedGraph
from .records import record_event
from .states import EVENT_PAUSED, PAUSE_BUDGET_LIMIT, ROUND_LIMIT_REASONS, STATUS_PAUSED

LOOP_CEILING_CONFIG_KEY = "workflow_run_loop_ceiling"
DEFAULT_LOOP_CEILING = 10
MAX_LOOP_CEILING = 100
BUDGET_CEILING_FACTOR = 3
BUDGET_KEYS = ("tokens", "cost_usd", "active_seconds", "tool_calls")


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


async def loop_ceiling(db: AsyncSession) -> int:
    raw = await get_system_config_value(db, LOOP_CEILING_CONFIG_KEY)
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return DEFAULT_LOOP_CEILING
    return value if 1 <= value <= MAX_LOOP_CEILING else DEFAULT_LOOP_CEILING


async def set_loop_ceiling(db: AsyncSession, value: int, *, user_id: str) -> int:
    if not 1 <= value <= MAX_LOOP_CEILING:
        raise ValueError(f"The loop ceiling must be between 1 and {MAX_LOOP_CEILING}.")
    await set_system_config_value(
        db, key=LOOP_CEILING_CONFIG_KEY, value=str(value),
        description="The highest iteration limit any workflow run loop may have.", )
    return value


def budget_values(raw: Any) -> dict[str, float]:
    values = raw if isinstance(raw, dict) else {}
    return {key: number for key in BUDGET_KEYS if (number := _positive_number(values.get(key))) is not None}


def validate_run_limits(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("run limits must be an object")
    unknown = set(raw) - {"loop_limit", "budget"}
    if unknown:
        raise ValueError(f"unknown run limit: {', '.join(sorted(unknown))}")
    limits: dict[str, Any] = {}
    if raw.get("loop_limit") is not None:
        if _positive_int(raw.get("loop_limit")) is None:
            raise ValueError("loop_limit must be a whole number of at least 1")
        limits["loop_limit"] = raw["loop_limit"]
    budget = raw.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or set(budget) - set(BUDGET_KEYS):
            raise ValueError(f"budget keys are: {', '.join(BUDGET_KEYS)}")
        cleaned = budget_values(budget)
        if len(cleaned) != len([value for value in budget.values() if value is not None]):
            raise ValueError("every budget value must be a positive number")
        if cleaned:
            limits["budget"] = cleaned
    return limits


MAX_PARENT_HOPS = 3


async def inherited_budget(db: AsyncSession, item: WorkItem | None) -> dict[str, float]:
    # Stories are created after the epic's budget was set; without inheritance they would run on the default budget.
    inherited: dict[str, float] = {}
    seen: set[str] = set()
    current = item
    for _ in range(MAX_PARENT_HOPS):
        if current is None:
            break
        seen.add(current.id)
        key = current.parent_key or current.epic_key
        if not key or key == current.source_key:
            break
        parent = (await db.execute(select(WorkItem).where(
            WorkItem.project_id == current.project_id,
            WorkItem.source_type == current.source_type, WorkItem.source_instance == current.source_instance,
            WorkItem.source_key == key))).scalar_one_or_none()
        if parent is None or parent.id in seen:
            break
        for name, value in budget_values(dict(parent.run_limits or {}).get("budget")).items():
            inherited.setdefault(name, value)
        current = parent
    return inherited


def patch_run_limits(current: Any, body: dict[str, Any]) -> dict[str, Any]:
    # A client sending only the budget must not erase the loop limit.
    merged = dict(current or {})
    if "loop_limit" in body:
        if body["loop_limit"] is None:
            merged.pop("loop_limit", None)
        else:
            merged["loop_limit"] = body["loop_limit"]
    if "budget" in body:
        if body["budget"] is None:
            merged.pop("budget", None)
        elif isinstance(body["budget"], dict):
            budget = dict(merged.get("budget") or {})
            for name, value in body["budget"].items():
                if value is None:
                    budget.pop(name, None)
                else:
                    budget[name] = value
            merged["budget"] = budget
        else:
            merged["budget"] = body["budget"]
    for name in set(body) - {"loop_limit", "budget"}:
        merged[name] = body[name]
    return validate_run_limits(merged)


async def initial_limits(db: AsyncSession, run: WorkflowRun, graph: PhasedGraph, *, item: WorkItem | None) -> None:
    ceiling = await loop_ceiling(db)
    item_limits = dict(getattr(item, "run_limits", None) or {}) if item is not None else {}
    override = _positive_int(item_limits.get("loop_limit"))
    run.loop_counters = {
        edge.id: {"title": edge.title or edge.id, "used": 0, "default": int(edge.max_iterations or 0),
                  "limit": min(override or int(edge.max_iterations or 0), ceiling),
                  "source": edge.source, "target": edge.target}
        for edge in graph.loop_edges()
    }
    workflow_budget = budget_values(graph.budget)
    budget_ceiling = {key: value * BUDGET_CEILING_FACTOR for key, value in workflow_budget.items()}
    item_budget = {**await inherited_budget(db, item), **budget_values(item_limits.get("budget"))}
    overrides = {key: min(value, budget_ceiling.get(key, value)) for key, value in item_budget.items()}
    run.limits = {
        "loop_ceiling": ceiling,
        "work_item_loop_limit": override,
        "budget": {**workflow_budget, **overrides},
        "budget_ceiling": budget_ceiling,
    }


def effective_loop_limit(run: WorkflowRun, edge: PhasedEdge) -> int:
    counter = dict(dict(run.loop_counters or {}).get(edge.id) or {})
    return int(counter.get("limit") or edge.max_iterations or 0)


async def refresh_budget_usage(db: AsyncSession, run: WorkflowRun, *, tool_calls: int = 0) -> list[str]:
    sessions = select(WorkflowRunSession.session_id).where(WorkflowRunSession.run_id == run.id)
    tokens, cost = (await db.execute(
        select(func.coalesce(func.sum(UsageEvent.tokens_in + UsageEvent.tokens_out), 0),
               func.coalesce(func.sum(UsageEvent.cost), 0))
        .where(UsageEvent.session_id.in_(sessions), UsageEvent.created_at >= run.created_at)
    )).one()
    usage = dict(run.budget_usage or {})
    now = utc_now()
    state = dict(run.node_state or {})
    mark = state.get("active_mark") or state.get("entered_at")
    if mark:
        elapsed = (ensure_utc(now) - ensure_utc(_parse(mark))).total_seconds()
        usage["active_seconds"] = round(float(usage.get("active_seconds") or 0) + max(elapsed, 0), 1)
    run.node_state = {**state, "active_mark": now.isoformat()}
    usage.update(tokens=int(tokens or 0), cost_usd=round(float(cost or 0), 6),
                 tool_calls=int(usage.get("tool_calls") or 0) + int(tool_calls))
    run.budget_usage = usage
    budget = dict(dict(run.limits or {}).get("budget") or {})
    return [key for key, value in budget.items() if float(usage.get(key) or 0) >= float(value)]


def _parse(value: Any):
    from datetime import datetime

    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def pause_message(run: WorkflowRun | None, reason: str, detail: dict[str, Any] | None) -> str:
    detail = dict(detail or {})
    return str(detail.get("message") or "").strip() or pause_text(run, reason, detail)


def pause_text(run: WorkflowRun | None, reason: str, detail: dict[str, Any]) -> str:
    from ..prompt_catalog.registry import prompt_key_registry
    from .run_texts import run_text

    if reason in ROUND_LIMIT_REASONS:
        edge = str(detail.get("edge_id") or "")
        counter = dict(dict(getattr(run, "loop_counters", None) or {}).get(edge) or {})
        return run_text(f"pause.{reason}", loop=str(counter.get("title") or edge or "a loop"),
                        used=str(detail.get("used") or counter.get("used") or "?"),
                        limit=str(detail.get("limit") or counter.get("limit") or "?"))
    if reason == PAUSE_BUDGET_LIMIT:
        return run_text("pause.budget_limit", keys=", ".join(str(key) for key in detail.get("keys") or []) or "?")
    return run_text(f"pause.{reason}" if f"run.pause.{reason}" in prompt_key_registry() else "pause.default")


async def pause_run(
    db: AsyncSession, run: WorkflowRun, *, reason: str, actor_id: str | None, detail: dict[str, Any]
) -> None:
    from .pause_causes import cause_of, split_reason

    reason = split_reason(reason, detail)  # a ``runtime_failed`` pause is stored as its class (``detail.code`` stays)
    from .uncertain import controls_in_pass

    if (unsure := controls_in_pass(run)) and "uncertain_checks" not in detail:
        detail = {**detail, "uncertain_checks": unsure}
    cause, rule = cause_of(reason, detail)
    detail = {**detail, "cause": cause, "cause_rule": rule}
    if not str(detail.get("message") or "").strip():
        detail["message"] = pause_text(run, reason, detail)
    run.status, run.pause_reason, run.waiting_kind = STATUS_PAUSED, reason, None
    run.node_state = {**dict(run.node_state or {}), "pause": {"reason": reason, **detail}}
    record_event(db, run, EVENT_PAUSED, node_id=run.current_node_id, actor_id=actor_id,
                 detail={"reason": reason, **detail})


__all__ = [
    "BUDGET_KEYS",
    "MAX_LOOP_CEILING",
    "DEFAULT_LOOP_CEILING",
    "LOOP_CEILING_CONFIG_KEY",
    "budget_values",
    "effective_loop_limit",
    "initial_limits",
    "loop_ceiling",
    "pause_message",
    "pause_run",
    "pause_text",
    "refresh_budget_usage",
    "set_loop_ceiling",
    "validate_run_limits",
]
