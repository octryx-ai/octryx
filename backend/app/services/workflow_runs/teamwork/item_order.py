"""Which teamwork items can start: plan order, merged dependencies, refusal waits, the executor and the findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ....time_utils import utc_now
from . import BLOCKED, CONFLICT, EXECUTOR_SERVER, FAILED, MERGED, PENDING, executors

MAX_START_REFUSALS = 3  # a start the device or the platform refused: two more tries of the same session, then failed
START_RETRY_SECONDS = 30  # the device channel checks every 30 s (``devices.jobs_channel.RESUME_CHECK_SECONDS``)
WAKE_KEY = "work_wake_at"  # node_state: when an item that waits (a backoff, a busy device) can start
REASON_START_REFUSED = "start_refused"


def _now() -> str:
    return utc_now().isoformat()


def _defaults() -> None:
    from . import server_items  # noqa: F401 - registers the server executor


async def choose_executor(db: Any, run: Any) -> str:
    """The first registered executor that takes this run (the device side registers ``device`` before ``server``)."""
    _defaults()
    for name, factory in executors().items():
        if await factory(db, run) is not None:
            return name
    return EXECUTOR_SERVER


async def executor_of(db: Any, run: Any, work: dict[str, Any]) -> Any:
    _defaults()
    factory = executors().get(str(work.get("executor") or EXECUTOR_SERVER)) or executors()[EXECUTOR_SERVER]
    return await factory(db, run) or await executors()[EXECUTOR_SERVER](db, run)


def plan_order(items: dict[str, dict[str, Any]]) -> list[str]:
    """Dependencies first; the coordinator's own order between independent items."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(key: str, path: tuple[str, ...]) -> None:
        if key in seen or key in path or key not in items:
            return
        for dep in items[key].get("depends_on") or []:
            visit(dep, (*path, key))
        seen.add(key)
        order.append(key)

    for key in items:
        visit(key, ())
    return order


def ready(items: dict[str, dict[str, Any]]) -> list[str]:
    """Pending items whose dependencies are all merged (some may still wait for their retry time)."""
    return [key for key in plan_order(items) if items[key].get("status") == PENDING
            and all(dict(items.get(dep) or {}).get("status") == MERGED for dep in items[key].get("depends_on") or [])]


def _due(item: dict[str, Any], now: datetime) -> bool:
    retry_at = _parse(item.get("retry_at"))
    return retry_at is None or retry_at <= now


def _parse(value: Any) -> datetime | None:
    """An ISO time as naive UTC (``utc_now``'s form)."""
    try:
        moment = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    return moment.astimezone(UTC).replace(tzinfo=None) if moment and moment.tzinfo else moment


def startable(items: dict[str, dict[str, Any]], now: datetime | None = None) -> list[str]:
    """Ready items whose retry time (after a refused start) has come."""
    moment = now or utc_now()
    return [key for key in ready(items) if _due(items[key], moment)]


def count_refusal(item: dict[str, Any], reason: str) -> None:
    """A start of ``item`` was refused before its agent ran: no attempt used, its session stays (the next start
    reuses it, never a new one), the next start waits ``START_RETRY_SECONDS`` × 2^(n-1); the
    ``MAX_START_REFUSALS``-th refusal makes the item ``failed`` with the reason (the coordinator re-plans with it)."""
    refusals = int(item.get("start_refusals") or 0) + 1
    detail = str(item.get("start_detail") or "")
    why = f"{reason}: {detail}" if detail and detail not in reason else reason
    item.update(start_refusals=refusals, job_id=None, attempts=max(0, int(item.get("attempts") or 0) - 1))
    if refusals >= MAX_START_REFUSALS:
        item.update(status=FAILED, retry_at=None, finished_at=_now(),
                    reason=f"its start was refused {refusals} times in a row (last: {why[:600]}); the item never ran")
        return
    retry_at = utc_now() + timedelta(seconds=START_RETRY_SECONDS * 2 ** (refusals - 1))
    item.update(status=PENDING, retry_at=retry_at.isoformat(), reason=f"{REASON_START_REFUSED}: {why[:600]}")


def _set_wake(run: Any, items: dict[str, dict[str, Any]]) -> None:
    """``node_state.work_wake_at``: the earliest time a ready item that waits can start (its retry time after a
    refused start, or the next device check for one the device could not take: busy, offline, paused); removed when
    none waits. An item waiting for a slot of this run's own jobs or for its worktree starts on that job's end."""
    from ..runtime_target.device_wait import WAITABLE_REASONS

    waits = [_parse(items[key].get("retry_at")) or utc_now() for key in ready(items)
             if items[key].get("retry_at") or items[key].get("reason") in WAITABLE_REASONS]
    state = dict(run.node_state or {})
    wake = min(waits).isoformat() if waits else None
    if state.get(WAKE_KEY) != wake:
        run.node_state = {**{k: v for k, v in state.items() if k != WAKE_KEY}, **({WAKE_KEY: wake} if wake else {})}


def findings(items: dict[str, dict[str, Any]]) -> list[str]:
    """One line per item that is not merged: what the coordinator re-plans with."""
    lines = []
    for key in plan_order(items):
        item = items[key]
        status = item.get("status")
        if status == MERGED:
            continue
        result = dict(item.get("result") or {})
        if status == CONFLICT:
            detail = f"its merge conflicts in {', '.join(item.get('conflicts') or [])}"
        elif status == BLOCKED:
            detail = f"blocked: {result.get('summary') or item.get('reason') or 'no reason given'}"
        elif status == PENDING:
            waits = [dep for dep in item.get("depends_on") or [] if dict(items.get(dep) or {}).get("status") != MERGED]
            detail = f"not started, waits for {', '.join(waits)}" if waits else "not started"
        else:
            detail = str(item.get("reason") or result.get("summary") or status)
        lines.append(f"item {key} ({item.get('role')}, {status}, iteration {item.get('iteration')}): {detail}")
    return lines
