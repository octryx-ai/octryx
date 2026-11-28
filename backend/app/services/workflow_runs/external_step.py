"""A platform step whose work runs outside the run's transaction."""

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
    run_id: str
    key: str
    token: str
    state_version: int
    node_id: str | None
    entry: Any
    facts: dict[str, Any] = field(default_factory=dict)


def pass_key(run: WorkflowRun, node_id: str | None = None) -> str:
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
    await db.refresh(run)
    moved = _moved(run, held, facts)
    if moved or not await reclaim_run(db, run):
        raise WorkflowRunError("run_moved_on", "The run changed while this step ran outside it "
                                               f"({', '.join(moved) or 'state_version'}); nothing more is recorded "
                                               "for this step.", 409)
    leases = _leases(run)
    leases.pop(held.key, None)
    run.context = {**dict(run.context or {}), IN_FLIGHT_KEY: leases}
