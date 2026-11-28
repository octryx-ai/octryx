import uuid
from datetime import timedelta

import pytest

from app.models import Session
from app.services.session.stream import session_run_started_at, session_stream_manager
from app.time_utils import ensure_utc, utc_now


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)


def test_session_run_started_at_prefers_persisted_root_run_start():
    root_started_at = utc_now() - timedelta(hours=2)
    current_turn_started_at = utc_now() - timedelta(seconds=10)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        status="running",
        metadata_={
            "run_started_at": root_started_at.isoformat(),
            "current_turn_started_at": current_turn_started_at.isoformat(),
        },
    )

    assert session_run_started_at(session) == ensure_utc(root_started_at)


def test_session_run_started_at_falls_back_to_current_turn_start():
    current_turn_started_at = utc_now() - timedelta(minutes=5)
    session = Session(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        status="running",
        metadata_={"current_turn_started_at": current_turn_started_at.isoformat()},
    )

    assert session_run_started_at(session) == ensure_utc(current_turn_started_at)


@pytest.mark.asyncio
async def test_session_stream_manager_emits_completion_notification_for_long_running_terminal_state():
    session_id = str(uuid.uuid4())
    websocket = _FakeWebSocket()

    await session_stream_manager.connect(session_id, websocket)
    await session_stream_manager.mark_run_started(
        session_id,
        started_at=utc_now() - timedelta(seconds=45),
        notification_scope="session",
    )

    try:
        await session_stream_manager.publish(
            session_id,
            "run_state",
            {
                "runStatus": "completed",
                "runCompletionReason": "completed",
            },
        )
    finally:
        await session_stream_manager.disconnect(session_id, websocket)
        await session_stream_manager.clear_run_tracking(session_id)

    assert [message["type"] for message in websocket.sent] == [
        "connected",
        "run_state",
        "completion_notification",
    ]
    notification = websocket.sent[-1]
    assert notification["policy"] == "long_running_completion_phase_1"
    assert notification["notificationScope"] == "session"
    assert notification["runStatus"] == "completed"
    assert notification["runCompletionReason"] == "completed"
    assert notification["elapsedSeconds"] >= 30


@pytest.mark.asyncio
async def test_session_stream_manager_skips_completion_notification_for_short_terminal_state():
    session_id = str(uuid.uuid4())
    websocket = _FakeWebSocket()

    await session_stream_manager.connect(session_id, websocket)
    await session_stream_manager.mark_run_started(
        session_id,
        started_at=utc_now() - timedelta(seconds=5),
        notification_scope="session",
    )

    try:
        await session_stream_manager.publish(
            session_id,
            "run_state",
            {
                "runStatus": "completed",
                "runCompletionReason": "completed",
            },
        )
    finally:
        await session_stream_manager.disconnect(session_id, websocket)
        await session_stream_manager.clear_run_tracking(session_id)

    assert [message["type"] for message in websocket.sent] == [
        "connected",
        "run_state",
    ]
