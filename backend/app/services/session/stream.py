from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketDisconnect

from ...models import Session
from ...time_utils import ensure_utc, utc_now_aware
from .api import resolve_session_stream_access
from .run_state import RUN_STATUS_IN_PROGRESS, get_session_run_status

_LONG_RUNNING_COMPLETION_THRESHOLD = timedelta(seconds=30)
_TERMINAL_RUN_STATUSES = frozenset({"completed", "failed", "stopped"})
_RUN_STARTED_AT_KEYS = ("run_started_at", "current_turn_started_at")


def session_run_started_at(session: Session | None) -> datetime | None:
    if session is None:
        return None
    metadata = dict(session.metadata_ or {})
    for key in _RUN_STARTED_AT_KEYS:
        parsed = _parse_metadata_datetime(metadata.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_metadata_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


class SessionStreamManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = defaultdict(set)
        self._active_run_tracking: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._subscribers[session_id].add(websocket)
        await self.publish(
            session_id,
            "connected",
            {
                "sessionId": session_id,
            },
            exclude={websocket},
        )
        await websocket.send_json({"type": "connected", "sessionId": session_id})

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(session_id)
            if not subscribers:
                return
            subscribers.discard(websocket)
            if not subscribers:
                self._subscribers.pop(session_id, None)

    async def mark_run_started(
        self,
        session_id: str,
        *,
        started_at=None,
        notification_scope: str = "session",
        root_session_id: str | None = None,
        coordinator_mode: str | None = None,
    ) -> None:
        started = ensure_utc(started_at) or utc_now_aware()
        async with self._lock:
            self._active_run_tracking[session_id] = {
                "started_at": started,
                "notification_scope": str(notification_scope or "session").strip().lower() or "session",
                "root_session_id": str(root_session_id or session_id).strip() or session_id,
                "coordinator_mode": str(coordinator_mode or "").strip().lower() or None,
            }

    async def clear_run_tracking(self, session_id: str) -> None:
        async with self._lock:
            self._active_run_tracking.pop(session_id, None)

    async def publish(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        exclude: set[WebSocket] | None = None,
    ) -> None:
        payload = dict(payload or {})
        notification_payload = await self._maybe_prepare_completion_notification(
            session_id=session_id,
            event_type=event_type,
            payload=payload,
        )
        async with self._lock:
            subscribers = list(self._subscribers.get(session_id, set()))
        if not subscribers:
            return
        message = {
            **payload,
            "type": event_type,
            "sessionId": session_id,
        }
        exclude = exclude or set()
        stale: list[WebSocket] = []
        for websocket in subscribers:
            if websocket in exclude:
                continue
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            with contextlib.suppress(Exception):
                await self.disconnect(session_id, websocket)
        if notification_payload is not None:
            await self.publish(session_id, "completion_notification", notification_payload)

    async def _maybe_prepare_completion_notification(
        self,
        *,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if event_type != "run_state":
            return None

        run_status = str(payload.get("runStatus") or payload.get("run_status") or "").strip().lower()
        if run_status == RUN_STATUS_IN_PROGRESS:
            notification_scope = str(payload.get("notificationScope") or payload.get("notification_scope") or "session")
            root_session_id = str(payload.get("rootSessionId") or payload.get("root_session_id") or session_id)
            coordinator_mode = str(payload.get("coordinatorMode") or payload.get("coordinator_mode") or "")
            await self.mark_run_started(
                session_id,
                notification_scope=notification_scope,
                root_session_id=root_session_id,
                coordinator_mode=coordinator_mode,
            )
            return None

        if run_status not in _TERMINAL_RUN_STATUSES:
            return None

        async with self._lock:
            tracking = dict(self._active_run_tracking.get(session_id) or {})
            self._active_run_tracking.pop(session_id, None)

        started_at = ensure_utc(tracking.get("started_at"))
        if started_at is None:
            return None
        elapsed = utc_now_aware() - started_at
        if elapsed < _LONG_RUNNING_COMPLETION_THRESHOLD:
            return None

        coordinator_mode = str(tracking.get("coordinator_mode") or payload.get("coordinatorMode") or "").strip().lower()
        completion_reason = str(payload.get("runCompletionReason") or payload.get("run_completion_reason") or "")
        return {
            "policy": "long_running_completion_phase_1",
            "notificationScope": str(tracking.get("notification_scope") or "session"),
            "rootSessionId": str(tracking.get("root_session_id") or session_id),
            "coordinatorMode": coordinator_mode or None,
            "runStatus": run_status,
            "runCompletionReason": completion_reason,
            "elapsedSeconds": int(max(0, elapsed.total_seconds())),
        }


session_stream_manager = SessionStreamManager()


async def serve_session_stream_websocket(*, db: AsyncSession, session_id: str, websocket: WebSocket) -> None:
    token = str(websocket.query_params.get("token") or "").strip()
    access_decision = await resolve_session_stream_access(db=db, session_id=session_id, token=token)
    if not access_decision.allowed:
        await websocket.close(code=1008, reason=access_decision.reason)
        return

    session = await db.get(Session, session_id)
    if session is not None:
        session_status = str(session.status or "").strip().lower()
        if session_status == "running" or get_session_run_status(session) == RUN_STATUS_IN_PROGRESS:
            await session_stream_manager.mark_run_started(session_id, started_at=session_run_started_at(session))
    await session_stream_manager.connect(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await session_stream_manager.disconnect(session_id, websocket)
