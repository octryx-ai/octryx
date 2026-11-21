"""A passed phase goes on into the next one inside the running turn (size class ``phase_change: same_turn``).

each phase change in the shared session of a small item ended the turn,
pushed the WIP, dispatched a new turn and resumed the same Claude session, about 20-30 s for nothing new. With the
class's ``phase_change: same_turn`` the Stop that passes a phase answers ``next_phase`` with the next phase's prompt;
the launcher blocks the Stop with it, so the agent goes on in the same turn and the platform takes the running turn as
the next phase's pass (its marker becomes that pass's ``started`` one). Only a launcher that says it can
(``capabilities``) gets it; every other one ends its turn.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

CAPABILITY = "next_phase"
STATE_NEXT_PHASE = "next_phase"
SAME_TURN = "same_turn"


async def continue_in_turn(db: AsyncSession, run: WorkflowRun, hook_input: dict[str, Any]) -> str:
    """The next phase's prompt when this Stop's turn goes on with it; ``""`` when the turn ends as usual."""
    from app.services.devices.job_state import ACTIVE_STATUSES

    from ...devices.jobs import thread_job
    from ..graph import NODE_PHASE, graph_for_run
    from ..records import main_session_id, record_event
    from ..run_texts import run_texts
    from ..states import STATUS_RUNNING
    from .continuation_marker import STATE_PENDING, STATE_STARTED, _marker, _set_marker
    from .run_session import next_phase_prompt, phase_change

    if CAPABILITY not in list(hook_input.get("capabilities") or []) or phase_change(run) != SAME_TURN:
        return ""
    marker = _marker(run)
    entry = dict(run.node_state or {}).get("entry")
    if (run.status != STATUS_RUNNING or marker.get("state") != STATE_PENDING
            or (marker.get("node_id"), marker.get("entry")) != (run.current_node_id, entry)):
        return ""
    node = (await graph_for_run(db, run)).nodes.get(str(run.current_node_id))
    thread_id = await main_session_id(db, run)
    busy = await thread_job(db, thread_id) if thread_id else None
    if node is None or node.kind != NODE_PHASE or busy is None or busy.status not in ACTIVE_STATUSES:
        return ""
    from ....time_utils import utc_now

    _set_marker(run, {**marker, "state": STATE_STARTED, "job_id": busy.id, "turn_id": busy.turn_id, "phase": True,
                      "started_at": utc_now().isoformat(), SAME_TURN: True})
    record_event(db, run, "device_continuation_started", node_id=node.id, detail={"job_id": busy.id, SAME_TURN: True})
    async with run_texts(db, run):
        return next_phase_prompt(run, node)


__all__ = ["CAPABILITY", "STATE_NEXT_PHASE", "continue_in_turn"]
