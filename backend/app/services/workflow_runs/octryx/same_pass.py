"""A paused phase pass goes on where it stopped: a worker who starts from zero again wastes the work already done.

The two pauses of an unfinished pass (``phase_not_finished``, ``phase_stalled``) keep what is
missing as the phase's delta (``gate_failure``, the first thing the next prompt names) and resume with
``{"kind": "continue"}``: the same pass, its own session resumed, the work in the folder kept.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

RESUME_CONTINUE = "continue"


def keep_delta(run: WorkflowRun, node_id: str, missing: str) -> None:
    """What the pass still lacks, as the phase's delta for its next prompt."""
    from ..run_texts import run_text
    from .gate_failure import record

    record(run, gate=run_text("same_pass.checks"), phase=node_id,
           failed=[SimpleNamespace(description=missing.strip() or run_text("same_pass.unknown"), detail="")])


def resume(node_id: str) -> dict[str, Any]:
    return {"kind": RESUME_CONTINUE, "node_id": node_id}


async def continue_pass(db: AsyncSession, run: WorkflowRun, node_id: str, *, actor_id: str | None) -> None:
    """The same pass of ``node_id`` goes on (a device thread resumes its session); anything else re-enters it."""
    from ....models import Session
    from ..engine import restart_at
    from ..records import main_session_id
    from ..states import STATUS_RUNNING
    from .continuation import continue_on_device
    from .continuation_marker import STATE_PENDING, _device_target, _set_marker

    thread_id = await main_session_id(db, run)
    thread = await db.get(Session, thread_id) if thread_id else None
    if run.current_node_id != node_id or _device_target(thread) is None:
        await restart_at(db, run, node_id, actor_id=actor_id)
        return
    run.status, run.waiting_kind = STATUS_RUNNING, None
    _set_marker(run, {"node_id": node_id, "entry": dict(run.node_state or {}).get("entry"), "state": STATE_PENDING})
    await continue_on_device(db, run)


UNFINISHED_KEY = "unfinished_pass"


async def continue_unfinished(db: AsyncSession, run: WorkflowRun, node_id: str) -> bool:
    """A turn that ended with the pass unfinished goes on by itself in the same pass, with its delta, until the same
    pass ended unfinished ``stall_after`` times (the workflow's data, as for identical stops); then it pauses.

    Example: the fix was green, the platform could not read the test output, and the run paused
    phase_not_finished for a person; the resume path alone (``continue``) still needed that person."""
    from .stop_stall import _stall_after

    entry = dict(run.node_state or {}).get("entry")
    last = dict(dict(run.context or {}).get(UNFINISHED_KEY) or {})
    times = int(last.get("times") or 0) + 1 if (last.get("node_id"), last.get("entry")) == (node_id, entry) else 1
    run.context = {**dict(run.context or {}), UNFINISHED_KEY: {"node_id": node_id, "entry": entry, "times": times}}
    if times >= await _stall_after(db, run, node_id):
        return False
    await continue_pass(db, run, node_id, actor_id=None)
    return True


__all__ = ["RESUME_CONTINUE", "UNFINISHED_KEY", "continue_pass", "continue_unfinished", "keep_delta", "resume"]
