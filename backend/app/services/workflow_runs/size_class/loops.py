"""Loop rounds per size class (``size_classes.<class>.max_rounds``) and escalation along ``escalate_to``."""

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
    rounds = None if _raised(run, edge_id) else _class_rounds(run, edge_id)
    return min(limit, rounds) if rounds is not None else limit


def escalate_at_limit(db: AsyncSession, run: WorkflowRun, edge_id: str, used: int, limit: int) -> int:
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
