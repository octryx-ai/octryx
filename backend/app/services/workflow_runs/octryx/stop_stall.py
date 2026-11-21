"""A stalled pass: the same missing checks twice with nothing done in between pauses the run or ends the item."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ....models import WorkflowRun

STALL_KEY = "stop_stall"
ITEM_STALL_KEY = "stop_stall_items"  # per teamwork item: items stop side by side
CODE_STALLED = "phase_stalled"


def _set_stall(run: WorkflowRun, value: dict[str, Any] | None) -> None:
    context = dict(run.context or {})
    if value is None:
        context.pop(STALL_KEY, None)
    else:
        context[STALL_KEY] = value
    run.context = context


#: ``"stall_after": N`` on the phase or its size class: the N-th identical stop with nothing done in between pauses
#: (a flow rule, so workflow data; without it the second one).
STALL_AFTER_KEY = "stall_after"
DEFAULT_STALL_AFTER = 2


async def _stall_after(db: AsyncSession, run: WorkflowRun, node_id: str) -> int:
    from ..graph import graph_for_run
    from ..size_class import class_config

    node = (await graph_for_run(db, run)).nodes.get(node_id)
    for source in (dict(getattr(node, "config", None) or {}), class_config(run)):
        value = source.get(STALL_AFTER_KEY)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
    return DEFAULT_STALL_AFTER


async def _stalled(db: AsyncSession, run: WorkflowRun, node_id: str, missing: str, attempts: int) -> bool:
    """Fail fast (weak models, few tokens): the same checks fail again with nothing done since the
    last stop — another forced pass would repeat it. The run pauses with the reason instead of the launcher's
    block cap spending up to four more passes (otherwise four identical failed passes in a row)."""
    from ..limits import pause_run
    from ..states import PAUSE_RUNTIME_FAILED

    entry = dict(run.node_state or {}).get("entry")
    progress = attempts  # every tool call the session made in this phase; reads are progress in a read phase
    last = dict(dict(run.context or {}).get(STALL_KEY) or {})
    same = (last.get("node_id"), last.get("entry"), last.get("missing")) == (node_id, entry, missing)
    stops = int(last.get("stops") or 1) + 1 if same and int(last.get("progress") or 0) >= progress else 1
    if stops < await _stall_after(db, run, node_id):
        _set_stall(run, {"node_id": node_id, "entry": entry, "missing": missing, "progress": progress,
                         "stops": stops})
        return False
    _set_stall(run, None)
    from .same_pass import keep_delta, resume

    keep_delta(run, node_id, missing)  # the same pass goes on with what is missing
    await pause_run(db, run, reason=PAUSE_RUNTIME_FAILED, actor_id=None, detail={
        "message": (f"The phase stopped {stops} times on the same missing checks with no tool call or answer between: "
                    f"{missing}. "
                    "Another pass would repeat it. Change the plan or the workflow's rules, run the phase again, "
                    "or abort the run."),
        "code": CODE_STALLED, "resume": resume(node_id)})
    return True


def _set_item_stall(run: WorkflowRun, key: str, value: dict[str, Any] | None) -> None:
    context = dict(run.context or {})
    stalls = {**dict(context.get(ITEM_STALL_KEY) or {}), key: value}
    context[ITEM_STALL_KEY] = {name: entry for name, entry in stalls.items() if entry is not None}
    run.context = context


async def _item_stalled(db: AsyncSession, run: WorkflowRun, key: str, session_id: str, missing: str,
                        attempts: int) -> bool:
    """A teamwork item stopping twice on the same missing checks with nothing done in between: the item fails with
    the reason (the coordinator re-plans with it); the run itself never pauses for one item.

    Each item keeps its own stall record: with one record for the run, items stopping side by side overwrote each
    other's, so a looping item was never seen as stalled and ran until the job's 60-minute limit."""
    from ..teamwork.item_results import item_finished

    entry = dict(run.node_state or {}).get("entry")
    last = dict(dict(dict(run.context or {}).get(ITEM_STALL_KEY) or {}).get(key) or {})
    marker = f"{run.current_node_id}/{key}"
    if not ((last.get("node_id"), last.get("entry"), last.get("missing")) == (marker, entry, missing)
            and int(last.get("progress") or 0) >= attempts):
        _set_item_stall(run, key, {"node_id": marker, "entry": entry, "missing": missing, "progress": attempts})
        return False
    _set_item_stall(run, key, None)
    await item_finished(db, run, key=key, session_id=session_id, state="failed",
                        reason=f"it stopped twice on the same missing checks with nothing done in between: {missing}")
    return True
