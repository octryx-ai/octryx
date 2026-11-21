"""A platform step whose work runs outside the run's transaction.

Some steps call a service that commits on its own (the Knowledge Source Sync commits its lease, its sync run and
its items). Run inside the run's transaction, such a commit silently ends the run claim — and on PostgreSQL the row
lock — while the step still believes it owns the run, and the ledger, the events and the engine's continuation
were then written against a run another writer may have stopped or moved meanwhile.

The contract here makes that boundary explicit:

1. :func:`release_for_external_work` — inside the claimed transaction: refuse when the same pass is already in
   flight (a second worker or a replay, ``action_in_flight``), record an in-flight lease for the idempotency key,
   **commit** (claim and row lock end here, on purpose and visibly) and return what the step held.
2. The caller runs the external work in its **own** session.
3. :func:`resume_after_external_work` — re-read the run and continue only if nothing moved: the same
   ``state_version``, status ``running``, node, entry, lease token and the facts the step depends on (the
   published page's id and version); then claim it again (compare-and-set) and clear the lease. Otherwise
   ``run_moved_on``: the caller writes nothing — no ledger, no event, no continuation.

A lease left by a crashed worker expires after :data:`LEASE_SECONDS`; the next activation of the pass runs again
(the external work is idempotent per pass: the Source Sync re-reads its scope).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .records import WorkflowRunError, reclaim_run
from .states import STATUS_RUNNING

IN_FLIGHT_KEY = "action_in_flight"
LEASE_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class HeldStep:
    """What the step owned when it released the run."""

    run_id: str
    key: str
    token: str
    state_version: int
    node_id: str | None
    entry: Any
    facts: dict[str, Any] = field(default_factory=dict)


def pass_key(run: WorkflowRun, node_id: str | None = None) -> str:
    """The idempotency key of the current pass through a node: ``<node id>#<entry>``."""
    return f"{node_id or run.current_node_id}#{dict(run.node_state or {}).get('entry') or 0}"


def _leases(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(IN_FLIGHT_KEY) or {})


def _live(lease: Any, now: datetime) -> bool:
    try:
        since = datetime.fromisoformat(str(dict(lease).get("since"))).replace(tzinfo=None)
    except (TypeError, ValueError):
        return False
    return now.replace(tzinfo=None) - since < timedelta(seconds=LEASE_SECONDS)


async def release_for_external_work(db: AsyncSession, run: WorkflowRun, *, key: str,
                                    facts: dict[str, Any]) -> HeldStep:
    """Lease the pass ``key``, commit, and return the held state (the run must be claimed by the caller)."""
    now = utc_now()
    lease = _leases(run).get(key)
    if lease is not None and _live(lease, now):
        raise WorkflowRunError("action_in_flight", "This step is already running for this pass; its result is "
                                                   "recorded when it returns.", 409)
    token = uuid.uuid4().hex
    run.context = {**dict(run.context or {}),
                   IN_FLIGHT_KEY: {**_leases(run), key: {"token": token, "since": now.isoformat()}}}
    held = HeldStep(run_id=run.id, key=key, token=token, state_version=int(run.state_version or 0),
                    node_id=run.current_node_id, entry=dict(run.node_state or {}).get("entry"), facts=dict(facts))
    await db.commit()  # the claim (and a PostgreSQL row lock) ends here, explicitly
    return held


def _moved(run: WorkflowRun, held: HeldStep, facts: dict[str, Any]) -> list[str]:
    lease = dict(_leases(run).get(held.key) or {})
    checks = (
        ("state_version", int(run.state_version or 0), held.state_version),
        ("status", run.status, STATUS_RUNNING),
        ("node", run.current_node_id, held.node_id),
        ("entry", dict(run.node_state or {}).get("entry"), held.entry),
        ("lease", lease.get("token"), held.token),
        *((f"fact:{name}", facts.get(name), value) for name, value in held.facts.items()),
    )
    return [name for name, now, then in checks if now != then]


async def resume_after_external_work(db: AsyncSession, run: WorkflowRun, held: HeldStep,
                                     facts: dict[str, Any]) -> None:
    """Re-claim the run for the step's result, or raise ``run_moved_on`` (write nothing)."""
    await db.refresh(run)
    moved = _moved(run, held, facts)
    if moved or not await reclaim_run(db, run):
        raise WorkflowRunError("run_moved_on", "The run changed while this step ran outside it "
                                               f"({', '.join(moved) or 'state_version'}); nothing more is recorded "
                                               "for this step.", 409)
    leases = _leases(run)
    leases.pop(held.key, None)
    run.context = {**dict(run.context or {}), IN_FLIGHT_KEY: leases}
