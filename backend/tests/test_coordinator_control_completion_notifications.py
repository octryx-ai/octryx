import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Session, User
from app.services.session.run_state import RUN_STATUS_IN_PROGRESS, set_session_run_state
from app.services.session.stream import session_stream_manager
from app.services.session.turn_tasks import CHAT_RUN_TASKS
from app.time_utils import utc_now


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_post_session_coordinator_control_stop_emits_long_running_completion_notification(
    client,
    auth_headers,
    db,
):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    root_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="running",
        metadata_={"title": "Coordinator Root"},
    )
    child_session = Session(
        id=str(uuid.uuid4()),
        user_id=admin.id,
        status="active",
        parent_session_id=root_session.id,
        sub_agent_depth=1,
    )
    set_session_run_state(root_session, RUN_STATUS_IN_PROGRESS)
    db.add_all([root_session, child_session])
    await db.commit()

    websocket = _FakeWebSocket()
    await session_stream_manager.connect(root_session.id, websocket)
    await session_stream_manager.mark_run_started(
        root_session.id,
        started_at=utc_now() - timedelta(seconds=45),
        notification_scope="coordinator",
        root_session_id=root_session.id,
        coordinator_mode="direct",
    )

    cancelled = asyncio.Event()

    async def blocking_task():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    CHAT_RUN_TASKS[root_session.id] = asyncio.create_task(blocking_task())

    try:
        response = await client.post(
            f"/api/v1/sessions/{child_session.id}/coordinator-control",
            headers=auth_headers,
            json={"action": "stop"},
        )
        await asyncio.wait_for(cancelled.wait(), timeout=1)
    finally:
        await session_stream_manager.disconnect(root_session.id, websocket)
        await session_stream_manager.clear_run_tracking(root_session.id)

    assert response.status_code == 200
    event_types = [message["type"] for message in websocket.sent]
    assert event_types == [
        "connected",
        "run_state",
        "completion_notification",
    ]
    run_state = websocket.sent[1]
    assert run_state["notificationScope"] == "coordinator"
    assert run_state["coordinatorMode"] == "direct"
    assert run_state["runStatus"] == "stopped"
    notification = websocket.sent[2]
    assert notification["notificationScope"] == "coordinator"
    assert notification["coordinatorMode"] == "direct"
    assert notification["runStatus"] == "stopped"
    assert notification["runCompletionReason"] == "user_cancelled"
    assert notification["elapsedSeconds"] >= 30
