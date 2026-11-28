"""Stop a chat turn that runs in another platform process."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from ...models import AuditLog
from ...models import Session as AgentSession
from ...time_utils import utc_now
from ..runtime_ownership.process_identity import current_process_id
from .turn_approval_state import CURRENT_TURN_STARTED_AT_KEY
from .turn_tasks import CHAT_RUN_TASKS

logger = logging.getLogger(__name__)

STOP_REQUEST_ACTION = "session.turn_stop_requested"
DEFAULT_POLL_SECONDS = 1.0
# Requests older than this are never acted on (a turn stopped long ago is settled by then).
REQUEST_WINDOW = timedelta(minutes=15)


def turn_marker(session: Any) -> str | None:
    metadata = session.metadata_ if isinstance(getattr(session, "metadata_", None), dict) else {}
    value = metadata.get(CURRENT_TURN_STARTED_AT_KEY) or metadata.get("run_started_at")
    return str(value) if value else None


def record_remote_stop_request(db: Any, session: Any) -> bool:
    # Call before the stop finalizes the session, which drops the turn marker; the caller commits.
    owner = str(getattr(session, "turn_owner_process_id", None) or "")
    if str(session.status or "").strip().lower() != "running" or not owner or owner == current_process_id():
        return False
    if not getattr(session, "user_id", None):
        return False
    db.add(
        AuditLog(
            user_id=session.user_id,
            session_id=session.id,
            action=STOP_REQUEST_ACTION,
            resource_type="session",
            resource_id=session.id,
            details={"owner_process_id": owner, "turn_marker": turn_marker(session)},
        )
    )
    return True


class RemoteTurnStopWatcher:
    def __init__(self, session_factory, *, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
        self._session_factory = session_factory
        self._poll_seconds = poll_seconds
        self._handled: dict[str, float] = {}  # request id -> monotonic time handled
        self._task: asyncio.Task | None = None

    def is_running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="remote-turn-stop-watcher")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_seconds)
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the next poll applies the same rule again
                logger.warning("remote_turn_stop_check_failed", extra={"error_type": type(exc).__name__})

    async def check_once(self) -> list[str]:
        live = {session_id: task for session_id, task in list(CHAT_RUN_TASKS.items()) if not task.done()}
        if not live:
            return []
        me = current_process_id()
        horizon = time.monotonic() - REQUEST_WINDOW.total_seconds()
        self._handled = {key: at for key, at in self._handled.items() if at >= horizon}
        async with self._session_factory() as db:
            requests = (
                await db.execute(
                    select(AuditLog.id, AuditLog.resource_id, AuditLog.details).where(
                        AuditLog.action == STOP_REQUEST_ACTION,
                        AuditLog.resource_id.in_(sorted(live)),
                        AuditLog.created_at >= utc_now() - REQUEST_WINDOW,
                    )
                )
            ).all()
            pending = [row for row in requests if row[0] not in self._handled]
            pending = [row for row in pending if str((row[2] or {}).get("owner_process_id") or "") == me]
            if not pending:
                return []
            sessions = {
                row.id: row
                for row in (
                    await db.execute(select(AgentSession).where(AgentSession.id.in_({row[1] for row in pending})))
                ).scalars()
            }
            markers = {session_id: turn_marker(session) for session_id, session in sessions.items()}
        cancelled: list[str] = []
        for request_id, session_id, details in pending:
            self._handled[request_id] = time.monotonic()
            requested_marker = (details or {}).get("turn_marker")
            current_marker = markers.get(session_id)
            if requested_marker and current_marker and requested_marker != current_marker:
                continue  # a request for an earlier turn of this session
            task = live.get(session_id)
            if task is None or task.done() or CHAT_RUN_TASKS.get(session_id) is not task:
                continue
            task.cancel()
            cancelled.append(session_id)
            logger.info("chat.turn.stop.remote_cancelled", extra={"session_id": session_id})
        return cancelled


__all__ = [
    "DEFAULT_POLL_SECONDS",
    "STOP_REQUEST_ACTION",
    "RemoteTurnStopWatcher",
    "record_remote_stop_request",
    "turn_marker",
]
