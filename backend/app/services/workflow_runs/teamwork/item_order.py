"""Which teamwork items can start: plan order, merged dependencies, refusal waits, the executor and the findings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ....time_utils import utc_now
from . import BLOCKED, CONFLICT, FAILED, MERGED, PENDING
from .work_types import SplitItem

MAX_START_REFUSALS = 3  # a start the device or the platform refused: two more tries of the same session, then failed
START_RETRY_SECONDS = 30  # the device channel checks every 30 s (``devices.jobs_channel.RESUME_CHECK_SECONDS``)
WAKE_KEY = "work_wake_at"
REASON_START_REFUSED = "start_refused"


def _now() -> str:
    return utc_now().isoformat()


async def executor_of(db: Any, run: Any) -> Any:
    from . import device_items

    return await device_items.executor_for(db, run)


def plan_order(items: dict[str, SplitItem]) -> list[str]:
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


def ready(items: dict[str, SplitItem]) -> list[str]:
    return [key for key in plan_order(items) if items[key].get("status") == PENDING
            and all(dict(items.get(dep) or {}).get("status") == MERGED for dep in items[key].get("depends_on") or [])]


def _due(item: SplitItem, now: datetime) -> bool:
    retry_at = _parse(item.get("retry_at"))
    return retry_at is None or retry_at <= now


def _parse(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None
    return moment.astimezone(UTC).replace(tzinfo=None) if moment and moment.tzinfo else moment


def startable(items: dict[str, SplitItem], now: datetime | None = None) -> list[str]:
    moment = now or utc_now()
    return [key for key in ready(items) if _due(items[key], moment)]


def count_refusal(item: dict[str, Any], reason: str) -> None:
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


def _set_wake(run: Any, items: dict[str, SplitItem]) -> None:
    from ..runtime_target.device_wait import WAITABLE_REASONS

    waits = [_parse(items[key].get("retry_at")) or utc_now() for key in ready(items)
             if items[key].get("retry_at") or items[key].get("reason") in WAITABLE_REASONS]
    state = dict(run.node_state or {})
    wake = min(waits).isoformat() if waits else None
    if state.get(WAKE_KEY) != wake:
        run.node_state = {**{k: v for k, v in state.items() if k != WAKE_KEY}, **({WAKE_KEY: wake} if wake else {})}


def findings(items: dict[str, SplitItem]) -> list[str]:
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
