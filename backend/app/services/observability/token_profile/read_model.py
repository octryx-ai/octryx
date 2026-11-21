"""A run's token profile for its Tokens view: per phase by category and by cache, the top consumers and the savings
hints. Read from the run's own events when the view is opened; no metric is read from the database.

``basis``: ``measured`` when every turn has the launcher's profile, ``estimated`` when none has, ``mixed`` otherwise;
each phase, consumer and hint says which it is.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from .catalog import categories
from .facts import groups
from .rules import hints
from .split import CATEGORY_KEYS, Split, Turn, fixed_start, hit_rate, split_turn
from .turns import run_turns

TOP_CONSUMERS = 10


async def _titles(db: AsyncSession, run: WorkflowRun) -> dict[str, str]:
    from ...workflow_runs.views import run_nodes

    try:
        nodes = await run_nodes(db, run, user=None)
    except Exception:  # noqa: BLE001 - a run of an unpublished flow still shows its tokens, by node id
        nodes = []
    return {str(node.get("id")): str(node.get("title") or node.get("id")) for node in nodes if node.get("id")}


def _pairs(turns: list[Turn]) -> list[tuple[Turn, Split]]:
    by_job: dict[str, list[Turn]] = defaultdict(list)
    for turn in turns:
        by_job[turn.job_id].append(turn)
    fixed = {job_id: fixed_start(job_turns) for job_id, job_turns in by_job.items()}
    return [(turn, split_turn(turn, fixed[turn.job_id])) for turn in turns]


def _phases(pairs: list[tuple[Turn, Split]]) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for turn, split in pairs:
        row = rows.setdefault(turn.node_id, {
            "phase": turn.node_id or "Unassigned", "turns": 0, "calls": 0, "measured_turns": 0,
            "categories": dict.fromkeys(CATEGORY_KEYS, 0), "by_tool": defaultdict(int),
            "cache": dict.fromkeys(("read", "write", "uncached", "output"), 0)})
        row["turns"] += 1
        row["calls"] += split.calls
        row["measured_turns"] += int(turn.measured)
        for name, value in split.categories.items():
            row["categories"][name] += value
        for tool, value in split.by_tool.items():
            row["by_tool"][tool] += value
        for name, value in split.cache.items():
            row["cache"][name] += value
    for row in rows.values():
        row["by_tool"] = dict(sorted(row["by_tool"].items(), key=lambda item: -item[1]))
        row["basis"] = _basis(row["measured_turns"], row["turns"])
        row["cache_hit_rate"] = hit_rate(row["cache"])
    return list(rows.values())


def _basis(measured: int, total: int) -> str:
    return "measured" if total and measured == total else "estimated" if not measured else "mixed"


def profile_of(turns: list[Turn]) -> dict[str, Any]:
    """The view's payload from the run's turns (pure: the turns carry their phase titles already)."""
    pairs = _pairs(turns)
    phase_rows = _phases(pairs)
    totals = {name: sum(row["cache"][name] for row in phase_rows) for name in ("read", "write", "uncached", "output")}
    consumers = sorted(groups(pairs), key=lambda row: -row["tokens"])[:TOP_CONSUMERS]
    return {
        "basis": _basis(sum(int(turn.measured) for turn in turns), len(turns)),
        "categories": categories(),
        "totals": {**totals, "input": totals["read"] + totals["write"] + totals["uncached"],
                   "cache_hit_rate": hit_rate(totals)},
        "phases": phase_rows,
        "consumers": consumers,
        "hints": hints(pairs),
    }


async def run_token_profile(db: AsyncSession, run: WorkflowRun) -> dict[str, Any]:
    turns = await run_turns(db, run.id)
    titles = await _titles(db, run)
    for turn in turns:
        turn.node_id = titles.get(turn.node_id, turn.node_id)
    return {"run_id": run.id, "workflow_key": run.workflow_key, "ticket_key": run.ticket_key, **profile_of(turns)}


__all__ = ["TOP_CONSUMERS", "profile_of", "run_token_profile"]
