"""A platform action that never finished: the requester retries the step instead of only aborting.

A platform action runs inside the request that reached its node. When that request dies before the action recorded
its result (a crash, a restarted pod), the run stays ``running`` at the action node with no further event. Without
this, runs hung at ``branch`` and offered only
"change where it runs", abort and "continue in a new chat".

The step counts as stalled when the run is ``running`` at a ``platform_action`` node, the current pass has no recorded
result (``action_ledger``) and no live in-flight lease (``external_step``), and the pass began
:data:`STALLED_AFTER_SECONDS` ago. **Retry the step** re-enters the node: a new pass, a new idempotency key, so the
action really runs again (``scm.create_branch`` adopts the branch an earlier pass created, ``branch_adoption``).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import User, WorkflowRun
from ...time_utils import utc_now
from .graph import NODE_PLATFORM_ACTION, graph_for_run
from .records import WorkflowRunError
from .states import STATUS_RUNNING

ACTION_RETRY_STEP = "retry_step"
# A platform action is one request's work (a provider call, a clone): one that has not recorded its result after this
# long is no longer running.
STALLED_AFTER_SECONDS = 5 * 60


def _entered_at(run: WorkflowRun) -> datetime | None:
    try:
        return datetime.fromisoformat(str(dict(run.node_state or {}).get("entered_at"))).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


async def stalled_action_node(db: AsyncSession, run: WorkflowRun) -> str | None:
    """The id of the platform action node the run is stalled at, or ``None``."""
    from .external_step import IN_FLIGHT_KEY, _live, pass_key

    if run.status != STATUS_RUNNING or not run.current_node_id:
        return None
    entered = _entered_at(run)
    now = utc_now().replace(tzinfo=None)
    if entered is None or now - entered < timedelta(seconds=STALLED_AFTER_SECONDS):
        return None
    context = dict(run.context or {})
    key = pass_key(run)
    lease = dict(context.get(IN_FLIGHT_KEY) or {}).get(key)
    if key in dict(context.get("action_ledger") or {}) or (lease is not None and _live(lease, now)):
        return None
    from .deferred_action import MARKER_KEY, _lease_over

    deferred = dict(context.get(MARKER_KEY) or {})
    if deferred.get("state") == "pending" or (deferred.get("state") == "started" and not _lease_over(deferred, now)):
        return None  # its executor runs it, or the sweep starts it again (``deferred_action``)
    node = (await graph_for_run(db, run)).nodes.get(run.current_node_id)
    return node.id if node is not None and node.kind == NODE_PLATFORM_ACTION else None


async def retry_step_action(db: AsyncSession, run: WorkflowRun) -> dict | None:
    if await stalled_action_node(db, run) is None:
        return None
    return {"key": ACTION_RETRY_STEP, "label": "Retry the step", "input": None}


async def retry_stalled_step(db: AsyncSession, run: WorkflowRun, *, user: User) -> None:
    """Run the stalled action node again (a new pass); refused when the step is not stalled."""
    from .engine import restart_at
    from .pause import record_decision

    node_id = await stalled_action_node(db, run)
    if node_id is None:
        raise WorkflowRunError("not_stalled", "The run is not stalled at a platform action.", 409)
    record_decision(db, run, kind="stalled_action", subject=STATUS_RUNNING, action=ACTION_RETRY_STEP,
                    payload={"action_node_id": node_id, "entry": dict(run.node_state or {}).get("entry")},
                    user_id=user.id)
    await restart_at(db, run, node_id, actor_id=user.id)


__all__ = ["ACTION_RETRY_STEP", "STALLED_AFTER_SECONDS", "retry_stalled_step", "retry_step_action",
           "stalled_action_node"]
