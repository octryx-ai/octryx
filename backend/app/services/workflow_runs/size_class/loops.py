"""Loop rounds per size class (``size_classes.<class>.max_rounds``) and escalation along ``escalate_to``.

Without classes, repro, fix, hands-on and review loops ran to their limits (31 loop iterations over 17 h)
and every limit paused the run for a person. A class may give a loop fewer rounds than the edge allows (one number
for every loop, or per loop edge id with "*" for the rest); when they are used up the run escalates to the class's
``escalate_to`` and goes on by itself in the same session, or pauses as at an edge limit when the class names none.
The workflow owner sets every number; the engine only compares.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun
from . import class_config, escalate


def _class_rounds(run: WorkflowRun, edge_id: str) -> int | None:
    rounds = class_config(run).get("max_rounds")
    if type(rounds) is int:
        return rounds
    if isinstance(rounds, dict):
        value = rounds.get(edge_id, rounds.get("*"))
        return value if type(value) is int else None
    return None


#: A loop counter a person gave more rounds at its pause: the class's rounds no longer bind that loop.
RAISED_KEY = "raised_by_person"


def _raised(run: WorkflowRun, edge_id: str) -> bool:
    return bool(dict(dict(run.loop_counters or {}).get(edge_id) or {}).get(RAISED_KEY))


def round_limit(run: WorkflowRun, edge_id: str, limit: int) -> int:
    """The loop's limit for the run's class now: the class's rounds when fewer than the edge's own (until a person
    gave the loop more rounds at its pause: then the counter's own limit)."""
    rounds = None if _raised(run, edge_id) else _class_rounds(run, edge_id)
    return min(limit, rounds) if rounds is not None else limit


def escalate_at_limit(db: AsyncSession, run: WorkflowRun, edge_id: str, used: int, limit: int) -> int:
    """The rounds already ``used`` that count after a class ran out of rounds on this loop and escalated.

    The next class's own rounds start again (0); a class without rounds of its own counts the rounds used so far
    against the edge's limit. A class without ``escalate_to`` leaves ``used`` as it is: the run pauses there."""
    if _raised(run, edge_id) or _class_rounds(run, edge_id) is None or used < round_limit(run, edge_id, limit):
        return used
    if not escalate(db, run, cause=f"loop_limit:{edge_id}"):
        return used
    if _class_rounds(run, edge_id) is None:
        return used
    counters = dict(run.loop_counters or {})
    counters[edge_id] = {**dict(counters.get(edge_id) or {}), "used": 0}
    run.loop_counters = counters
    return 0


__all__ = ["RAISED_KEY", "escalate_at_limit", "round_limit"]
