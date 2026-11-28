"""The session stream and canvas endpoints and websockets require session access and block observer mutations."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.api.routes.sessions._sessions_sharing_routes import session_stream_ws
from app.api.routes.sessions.canvas import canvas_ws, create_canvas, get_canvas
from app.models import Role, Session, SessionCollaborator, User, UserRole
from app.services.auth import create_session_stream_token, hash_password
from app.services.canvas import canvas_manager


class _FakeWebSocket:
    def __init__(self, token: str):
        self.query_params = {"token": token}
        self.accepted = False
        self.closed = None
        self.sent_messages: list[dict] = []
        self.received = 0

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent_messages.append(payload)

    async def close(self, code: int, reason: str = ""):
        self.closed = (code, reason)

    async def receive_text(self):
        self.received += 1
        raise RuntimeError("stop")


class _FakeCanvasWebSocket:
    def __init__(self, token: str, messages: list[dict] | None = None):
        self.query_params = {"token": token}
        self.cookies: dict[str, str] = {}
        self.accepted = False
        self.closed = None
        self.sent_messages: list[dict] = []
        self._messages = list(messages or [])

    async def accept(self):
        self.accepted = True

    async def send_json(self, payload):
        self.sent_messages.append(payload)

    async def close(self, code: int, reason: str = ""):
        self.closed = (code, reason)

    async def receive_json(self):
        if self._messages:
            return self._messages.pop(0)
        raise WebSocketDisconnect()


@pytest.mark.asyncio
async def test_session_stream_ws_allows_observer_collaborator(db, auth_user):
    observer = User(
        id=str(uuid.uuid4()),
        username="observer-user",
        email="observer@example.com",
        password_hash=hash_password("secret123"),
        display_name="Observer User",
        is_active=True,
    )
    db.add(observer)
    session = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.flush()
    db.add(
        SessionCollaborator(
            session_id=session.id,
            user_id=observer.id,
            role="observer",
            invited_by=auth_user.id,
        )
    )
    await db.commit()

    token = create_session_stream_token(user_id=observer.id, session_id=session.id)
    websocket = _FakeWebSocket(token)
    await session_stream_ws(session.id, websocket, db)
    assert websocket.accepted is True
    assert websocket.closed is None
    assert websocket.sent_messages
    assert websocket.sent_messages[0]["type"] == "connected"


@pytest.mark.asyncio
async def test_canvas_endpoints_require_session_access(client, db, auth_user):
    viewer_role = (await db.execute(select(Role).where(Role.name == "viewer"))).scalar_one()
    outsider = User(
        id=str(uuid.uuid4()),
        username="canvas-outsider",
        email="canvas-outsider@example.com",
        password_hash=hash_password("secret123"),
        display_name="Canvas Outsider",
        is_active=True,
    )
    db.add(outsider)
    await db.flush()
    db.add(UserRole(user_id=outsider.id, role_id=viewer_role.id))
    session = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.commit()

    outsider_auth = await client.post(
        "/api/v1/auth/login", data={"username": "canvas-outsider", "password": "secret123"}
    )
    assert outsider_auth.status_code == 200
    outsider_headers = {"Authorization": f"Bearer {outsider_auth.json()['access_token']}"}

    create_resp = await client.post(f"/api/v1/canvas/sessions/{session.id}", headers=outsider_headers)
    assert create_resp.status_code == 404

    get_resp = await client.get(f"/api/v1/canvas/sessions/{session.id}", headers=outsider_headers)
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_canvas_ws_blocks_observer_mutation(db, auth_user):
    canvas_manager._canvases.clear()
    observer = User(
        id=str(uuid.uuid4()),
        username="canvas-observer",
        email="canvas-observer@example.com",
        password_hash=hash_password("secret123"),
        display_name="Canvas Observer",
        is_active=True,
    )
    db.add(observer)
    session = Session(id=str(uuid.uuid4()), user_id=auth_user.id, agent_type="diagnosis", status="active")
    db.add(session)
    await db.flush()
    db.add(
        SessionCollaborator(
            session_id=session.id,
            user_id=observer.id,
            role="observer",
            invited_by=auth_user.id,
        )
    )
    await db.commit()

    canvas_payload = await create_canvas(session.id, current_user=auth_user, db=db)
    canvas_id = str(canvas_payload["canvas_id"])

    observer_canvas = await get_canvas(session.id, current_user=observer, db=db)
    assert observer_canvas["canvas_id"] == canvas_id

    token = create_session_stream_token(user_id=observer.id, session_id=session.id)
    websocket = _FakeCanvasWebSocket(token, messages=[{"type": "draw", "element": {"shape": "rect"}}])
    await canvas_ws(canvas_id, websocket, db)

    assert websocket.accepted is True
    assert websocket.closed == (1008, "Contributor access required")
    canvas = canvas_manager.get_canvas(canvas_id)
    assert canvas is not None
    assert canvas.elements == []
