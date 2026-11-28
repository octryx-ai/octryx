"""A change of plan goes back with the work of its time."""

from __future__ import annotations

import re
from typing import Any

from ...time_utils import utc_now

CHECKPOINTS_KEY = "wip_at_entry"
RESET_KEY = "wip_reset"
EVENT_REQUESTED = "wip_reset_requested"
EVENT_DONE = "wip_reset_done"
_SHA = re.compile(r"^[0-9a-f]{40}$")


def note_phase_entry(run: Any, node_id: str) -> None:
    context = dict(run.context or {})
    sha = str(dict(context.get("wip") or {}).get("sha") or "")
    if not _SHA.match(sha):
        return
    run.context = {**context, CHECKPOINTS_KEY: {**dict(context.get(CHECKPOINTS_KEY) or {}), node_id: sha}}


def request_reset(run: Any, plan: str, ordered_phases: list[str]) -> str:
    context = dict(run.context or {})
    checkpoints = dict(context.get(CHECKPOINTS_KEY) or {})
    later = ordered_phases[ordered_phases.index(plan) + 1:] if plan in ordered_phases else []
    sha = next((str(checkpoints[node]) for node in later if _SHA.match(str(checkpoints.get(node) or ""))), "")
    if sha:
        run.context = {**context, RESET_KEY: {"sha": sha, "node_id": plan, "at": utc_now().isoformat()}}
    return sha


def pending_reset(run: Any) -> str:
    return str(dict(dict(run.context or {}).get(RESET_KEY) or {}).get("sha") or "")


def reset_reported(run: Any, report: dict[str, Any]) -> dict[str, Any] | None:
    done = report.get("wip_reset") if isinstance(report.get("wip_reset"), dict) else None
    sha = pending_reset(run)
    if not done or not sha or done.get("sha") != sha or done.get("state") != "done":
        return None
    context = dict(run.context or {})
    context.pop(RESET_KEY, None)
    run.context = context
    return done


__all__ = ["CHECKPOINTS_KEY", "EVENT_DONE", "EVENT_REQUESTED", "RESET_KEY", "note_phase_entry", "pending_reset",
           "request_reset", "reset_reported"]
