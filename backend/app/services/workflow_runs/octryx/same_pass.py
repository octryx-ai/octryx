"""A paused phase pass goes on where it stopped: a worker who starts from zero again wastes the work already done."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

RESUME_CONTINUE = "continue"


def keep_delta(run: WorkflowRun, node_id: str, missing: str) -> None:
    from ..run_texts import run_text
    from .gate_failure import record

    record(run, gate=run_text("same_pass.checks"), phase=node_id,
           failed=[SimpleNamespace(description=missing.strip() or run_text("same_pass.unknown"), detail="")])


def resume(node_id: str) -> dict[str, Any]:
    return {"kind": RESUME_CONTINUE, "node_id": node_id}


async def continue_pass(db: AsyncSession, run: WorkflowRun, node_id: str, *, actor_id: str | None) -> None:
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
