"""Live nudges for the companion: one WebSocket channel per person, process-local (polling stays the fallback).

The channel carries only ``{type: "attention_changed", run_id?, state?}``; the UI then re-reads
``GET /api/v1/attention``. Producers call :func:`nudge_after_commit` inside their transaction: the nudge goes out
only when the change is committed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
EVENT_TYPE = "attention_changed"
JOB_EVENT_TYPE = "job_changed"
_PENDING_KEY = "attention_nudges"
NUDGE_EVENT_KINDS: frozenset[str] = frozenset(
    json.loads((Path(__file__).with_name("nudge_events.json")).read_text(encoding="utf-8"))["kinds"])


class UserStreamManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._watchers: dict[str, set[WebSocket]] = defaultdict(set)  # run id → sockets watching it (read access)
        self._lock = asyncio.Lock()

    async def watch(self, run_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._watchers[run_id].add(websocket)

    async def unwatch(self, run_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            sockets = self._watchers.get(run_id)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self._watchers.pop(run_id, None)

    async def unwatch_all(self, websocket: WebSocket) -> None:
        async with self._lock:
            for run_id in [key for key, sockets in self._watchers.items() if websocket in sockets]:
                self._watchers[run_id].discard(websocket)
                if not self._watchers[run_id]:
                    self._watchers.pop(run_id, None)

    async def publish_job(self, run_id: str) -> None:
        async with self._lock:
            watchers = list(self._watchers.get(run_id, set()))
        for websocket in watchers:
            try:
                await websocket.send_json({"type": JOB_EVENT_TYPE, "run_id": run_id})
            except Exception:  # noqa: BLE001 - a closed socket is dropped
                await self.unwatch_all(websocket)

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._subscribers[user_id].add(websocket)
        await websocket.send_json({"type": "connected"})

    async def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(user_id)
            if subscribers is not None:
                subscribers.discard(websocket)
                if not subscribers:
                    self._subscribers.pop(user_id, None)

    async def publish(self, user_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(user_id, set()))
        for websocket in subscribers:
            try:
                await websocket.send_json({"type": EVENT_TYPE, **payload})
            except Exception:  # noqa: BLE001 - a closed socket is dropped
                await self.disconnect(user_id, websocket)

    def clear(self) -> None:
        self._subscribers.clear()
        self._watchers.clear()


user_stream_manager = UserStreamManager()


def nudge_after_commit(db: AsyncSession, user_id: str | None, **payload: Any) -> None:
    """Nudge ``user_id``'s companion once this transaction commits (dropped on rollback)."""
    if not user_id:
        return
    _queue(db, user_id, {key: value for key, value in payload.items() if value is not None})


def job_changed_after_commit(db: AsyncSession, run_id: str) -> None:
    """Tell only the sockets watching ``run_id`` once this transaction commits; nobody's queue is nudged."""
    _queue(db, None, {"run_id": run_id})


def _queue(db: AsyncSession, user_id: str | None, payload: dict[str, Any]) -> None:
    sync = db.sync_session
    sync.info.setdefault(_PENDING_KEY, []).append((user_id, payload))
    if not event.contains(sync, "after_commit", _publish_pending):
        event.listen(sync, "after_commit", _publish_pending)
        event.listen(sync, "after_rollback", _drop_pending)


def _publish_pending(sync_session: Any) -> None:
    pending = sync_session.info.pop(_PENDING_KEY, [])
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for user_id, payload in pending:
        if user_id:
            loop.create_task(user_stream_manager.publish(user_id, payload))
    for run_id in {payload.get("run_id") for _user_id, payload in pending if payload.get("run_id")}:
        loop.create_task(user_stream_manager.publish_job(run_id))


def _drop_pending(sync_session: Any) -> None:
    sync_session.info.pop(_PENDING_KEY, None)


__all__ = ["EVENT_TYPE", "JOB_EVENT_TYPE", "NUDGE_EVENT_KINDS", "UserStreamManager", "job_changed_after_commit",
           "nudge_after_commit", "user_stream_manager"]
