"""Where the tokens go, for Prometheus and Grafana: counted when a turn's ``token_profile`` arrives, in this process,
never through the database."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..metric_types import Counter, Histogram
from .assemble import TurnFacts
from .facts import short_tool
from .split import Turn, fixed_start, hit_rate, split_turn

TOKENS = Counter("octryx_tokens_total", "Input tokens of device turns by workflow, size class, phase, category "
                 "(system_and_tools, prompt, tool_results, history, subagents, output) and tool (tool results, else "
                 "none)",
                 ("workflow", "size_class", "phase", "effort", "category", "tool"), max_series=2000)
CACHE = Counter("octryx_token_cache_total", "Tokens of device turns by workflow, size class, phase and kind (read, "
                "write, uncached, output)", ("workflow", "size_class", "phase", "effort", "kind"))
CALLS = Counter("octryx_token_calls_total", "Model calls of device turns in the main thread by workflow, size class "
                "and phase (measured turns only): system_and_tools / calls is the fixed start per call",
                ("workflow", "size_class", "phase", "effort"))
HIT_RATIO = Histogram("octryx_token_cache_hit_ratio", "Per device turn, the share of its input tokens read from the "
                      "prompt cache, by workflow, size class and phase",
                      ("workflow", "size_class", "phase", "effort"),
                      buckets=(0.1, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99))
METRICS = (TOKENS, CACHE, CALLS, HIT_RATIO)

_REMEMBERED = 2000
_PARTS: OrderedDict[tuple[str, str], TurnFacts] = OrderedDict()
_FIRST_TURNS: OrderedDict[str, list[Turn]] = OrderedDict()


def _remember(store: OrderedDict, key: Any, value: Any) -> Any:
    store.setdefault(key, value)
    store.move_to_end(key)
    while len(store) > _REMEMBERED:
        store.popitem(last=False)
    return store[key]


def _labels(session_id: str, effort: str) -> dict[str, str]:
    from .. import live_state

    context = live_state.run_context(session_id) or {}
    return {"workflow": context.get("workflow") or "none", "size_class": context.get("size_class") or "none",
            "phase": context.get("phase") or "none", "effort": effort or "default"}


def count(turn: Turn, fixed: int, labels: dict[str, str]) -> None:
    split = split_turn(turn, fixed)
    for category, value in split.categories.items():
        if category != "tool_results" and value:
            TOKENS.inc(value, **labels, category=category, tool="none")
    for tool, value in split.by_tool.items():
        if value:
            TOKENS.inc(value, **labels, category="tool_results", tool=short_tool(tool))
    for kind, value in split.cache.items():
        if value:
            CACHE.inc(value, **labels, kind=kind)
    if turn.main_calls:
        CALLS.inc(len(turn.main_calls), **labels)
    rate = hit_rate(split.cache)
    if rate is not None:
        HIT_RATIO.observe(rate, **labels)


async def observe(db: AsyncSession, job: Any, body: dict[str, Any]) -> None:
    from ..agent_metrics import on_commit

    turn_id = str(body.get("turn_id") or "")
    parts = int(body.get("parts") or 1)
    key = (str(job.id), turn_id)
    facts = _remember(_PARTS, key, TurnFacts(str(job.id), turn_id))
    facts.add(body)
    if len(facts.parts) < parts:
        return
    _PARTS.pop(key, None)
    turn = facts.build()
    seen = _remember(_FIRST_TURNS, str(job.id), [])
    if not seen:
        seen.append(turn)
    session_id, effort = str(job.session_id), str(getattr(job, "turn_effort", None) or "")
    await _learn(db, session_id, turn)
    fixed = fixed_start(seen)
    # The labels at the commit, when this transaction's own run and phase changes are in memory too.
    on_commit(db, lambda: count(turn, fixed, _labels(session_id, effort)))


async def _learn(db: AsyncSession, session_id: str, turn: Turn) -> None:
    import logging

    from ...workflow_runs.run_memory import large_outputs

    if not turn.measured:
        return
    try:
        async with db.begin_nested():
            await large_outputs(db, session_id, turn.tools)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("run_memory_large_output_failed", exc_info=True)


def reset() -> None:
    for metric in METRICS:
        metric.series.clear()
    _PARTS.clear()
    _FIRST_TURNS.clear()


__all__ = ["CACHE", "CALLS", "HIT_RATIO", "METRICS", "TOKENS", "count", "observe", "reset"]
