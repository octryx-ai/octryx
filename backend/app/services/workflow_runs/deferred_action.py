"""Slow repository actions run after the request that reached them, never inside it."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import WorkflowRun
from ...time_utils import utc_now
from .graph import FAILED, PhasedNode
from .platform import catalog
from .records import WorkflowRunError, record_event
from .states import EVENT_WAITING, STATUS_RUNNING

logger = logging.getLogger(__name__)

DEFERRED_ACTIONS = frozenset({catalog.SCM_CREATE_BRANCH, catalog.SCM_CHECKOUT})
MARKER_KEY = "deferred_action"
STATE_PENDING, STATE_STARTED = "pending", "started"
LEASE_SECONDS = 10 * 60  # a started step whose executor is gone is started again after this
MAX_ATTEMPTS = 3
POOL_SHARE = 3  # deferred steps hold at most 1/POOL_SHARE of the pool; the rest stays for requests
_SLOTS: dict[int, asyncio.Semaphore] = {}  # per event loop (a semaphore belongs to the loop it first waits in)
_AFTER_COMMIT_KEY = "workflow_deferred_actions"
_EXECUTING: ContextVar[bool] = ContextVar("octryx_deferred_action_executing", default=False)
# The suite runs these steps inline (``tests/conftest.py``, like ``health_checks.PERSIST_INLINE``); tests marked
# ``deferred_actions`` pin the deferral itself.
RUN_INLINE = False


def is_deferred(key: str) -> bool:
    return key in DEFERRED_ACTIONS and not _EXECUTING.get() and not RUN_INLINE


def _marker(run: WorkflowRun) -> dict[str, Any]:
    return dict(dict(run.context or {}).get(MARKER_KEY) or {})


def _set_marker(run: WorkflowRun, marker: dict[str, Any] | None) -> None:
    context = {key: value for key, value in dict(run.context or {}).items() if key != MARKER_KEY}
    run.context = {**context, MARKER_KEY: marker} if marker else context


def _current_pass(run: WorkflowRun, marker: dict[str, Any]) -> bool:
    return (run.status == STATUS_RUNNING and bool(marker)
            and (marker.get("node_id"), marker.get("entry")) == (run.current_node_id,
                                                                 dict(run.node_state or {}).get("entry")))


def _lease_over(marker: dict[str, Any], now: datetime) -> bool:
    try:
        since = datetime.fromisoformat(str(marker.get("since"))).replace(tzinfo=None)
    except (TypeError, ValueError):
        return True
    return now.replace(tzinfo=None) - since >= timedelta(seconds=LEASE_SECONDS)


def _startable(run: WorkflowRun, marker: dict[str, Any], now: datetime) -> bool:
    if not _current_pass(run, marker):
        return False
    return marker.get("state") == STATE_PENDING or (marker.get("state") == STATE_STARTED and _lease_over(marker, now))


async def defer(db: AsyncSession, run: WorkflowRun, node: PhasedNode, key: str, *, actor_id: str | None) -> None:
    _set_marker(run, {"node_id": node.id, "entry": dict(run.node_state or {}).get("entry"), "action": key,
                      "state": STATE_PENDING, "attempts": 0, "actor_id": actor_id})
    record_event(db, run, EVENT_WAITING, node_id=node.id, detail={"action": key, "deferred": True})
    _after_commit(db, run.id)


def _after_commit(db: AsyncSession, run_id: str) -> None:
    sync = db.sync_session
    sync.info.setdefault(_AFTER_COMMIT_KEY, set()).add(run_id)
    if not event.contains(sync, "after_commit", _schedule_pending):
        event.listen(sync, "after_commit", _schedule_pending)
        event.listen(sync, "after_rollback", _drop_pending)


def _schedule_pending(sync_session: Any) -> None:
    for run_id in sync_session.info.pop(_AFTER_COMMIT_KEY, set()):
        schedule(run_id)


def _drop_pending(sync_session: Any) -> None:
    sync_session.info.pop(_AFTER_COMMIT_KEY, None)


def schedule(run_id: str, *, session_factory=None) -> None:
    from ..chat_turn_background import schedule_chat_turn_background_task

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    schedule_chat_turn_background_task(session_id=run_id, task_name="workflow_deferred_action",
                                       coro_factory=lambda: execute(run_id, session_factory=session_factory))


def max_concurrent() -> int:
    from ...config import get_settings

    settings = get_settings()
    return max(1, (int(settings.db_pool_size) + int(settings.db_max_overflow)) // POOL_SHARE)


def executor_slots() -> asyncio.Semaphore:
    return _SLOTS.setdefault(id(asyncio.get_running_loop()), asyncio.Semaphore(max_concurrent()))


async def _claim(db: AsyncSession, run_id: str) -> tuple[str, str] | None:
    from .records import lock_run

    run = await db.get(WorkflowRun, run_id)
    if run is None or not _startable(run, _marker(run), utc_now()):
        return None
    run = await lock_run(db, run)
    marker = _marker(run)
    now = utc_now()
    if not _startable(run, marker, now):
        return None
    attempts = int(marker.get("attempts") or 0) + 1
    token = uuid.uuid4().hex
    _set_marker(run, {**marker, "state": STATE_STARTED, "token": token, "since": now.isoformat(),
                      "attempts": attempts})
    return token, str(run.repository or "")


async def _give_up(db: AsyncSession, run: WorkflowRun, node: PhasedNode, marker: dict[str, Any]) -> None:
    from .action_failures import record_failure
    from .engine import resolve_current_node
    from .engine_context import _set_context
    from .platform.dispatch import CLASS_EXTERNAL

    label = str(marker.get("action") or "")
    reason = f"the step did not finish in {MAX_ATTEMPTS} attempts"
    record_failure(run, node_id=node.id, action=label, reason=reason, failure_class=CLASS_EXTERNAL)
    _set_context(run, "actions", node.id, {"action": label, "result": FAILED, "reason": reason,
                                           "failure_class": CLASS_EXTERNAL})
    _set_marker(run, None)
    await resolve_current_node(db, run, FAILED, actor_id=marker.get("actor_id"))


async def _run_step(db: AsyncSession, run_id: str, token: str) -> None:
    from .engine import graph_for_run, resolve_current_node
    from .platform_actions import WAIT, run_platform_action
    from .records import lock_run

    run = await db.get(WorkflowRun, run_id)
    if run is None:
        return
    run = await lock_run(db, run)
    marker = _marker(run)
    if marker.get("token") != token or not _current_pass(run, marker):
        return  # the run moved on (aborted, restarted) or another executor took the lease: write nothing
    node = (await graph_for_run(db, run)).nodes.get(str(marker["node_id"]))
    if node is None:
        _set_marker(run, None)
        return
    if int(marker.get("attempts") or 0) > MAX_ATTEMPTS:
        await _give_up(db, run, node, marker)
        return
    _set_marker(run, None)
    flag = _EXECUTING.set(True)
    try:
        route = await run_platform_action(db, run, node)
    finally:
        _EXECUTING.reset(flag)
    if route != WAIT:
        await resolve_current_node(db, run, route, actor_id=marker.get("actor_id"))


async def execute(run_id: str, *, session_factory=None) -> None:
    from ...db import core as db_core

    factory = session_factory or db_core.async_session_factory
    async with factory() as db:
        try:
            claimed = await _claim(db, run_id)
        except WorkflowRunError:
            return  # the run is changing right now; the sweep looks again
        await db.commit()
    if claimed is None:
        return
    token, _repository = claimed
    async with executor_slots():
        async with factory() as db:
            try:
                await _run_step(db, run_id, token)
                await db.commit()
            except Exception:  # noqa: BLE001 - the lease stays; the sweep starts the step again after it ends
                await db.rollback()
                logger.warning("workflow_run.deferred_action_failed run_id=%s", run_id, exc_info=True)


async def sweep_deferred_actions(db: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or utc_now()
    runs = (await db.execute(select(WorkflowRun).where(WorkflowRun.status == STATUS_RUNNING))).scalars().all()
    due = [run.id for run in runs if _startable(run, _marker(run), now)]
    for run_id in due:
        schedule(run_id)
    return len(due)


__all__ = ["DEFERRED_ACTIONS", "LEASE_SECONDS", "MARKER_KEY", "defer", "execute", "executor_slots", "is_deferred",
           "max_concurrent", "schedule", "sweep_deferred_actions"]
