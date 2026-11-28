"""The session stream websocket requires a valid token for the same session with session access and then receives published events."""

import asyncio
import uuid

import pytest
from starlette.datastructures import QueryParams
from starlette.websockets import WebSocketDisconnect

from app.api.routes.sessions._sessions_sharing_routes import session_stream_ws
from app.services.auth import create_session_stream_token
from app.services.session.stream import session_stream_manager


class FakeWebSocket:
    def __init__(self, token: str):
        self.query_params = QueryParams({"token": token})
        self.accepted = False
        self.closed = None
        self.sent = []
        self._incoming: asyncio.Queue[str] = asyncio.Queue()

    async def accept(self):
        self.accepted = True

    async def close(self, code: int, reason: str | None = None):
        self.closed = {"code": code, "reason": reason}

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive_text(self):
        item = await self._incoming.get()
        if item == "__disconnect__":
            raise WebSocketDisconnect(code=1000)
        return item

    def disconnect(self):
        self._incoming.put_nowait("__disconnect__")


@pytest.mark.asyncio
async def test_session_stream_websocket_requires_valid_session_token(client, auth_headers, db):
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]
    websocket = FakeWebSocket("invalid-token")

    await session_stream_ws(session_id, websocket, db=db)
    assert websocket.closed is not None
    assert websocket.closed["code"] == 1008
    assert websocket.closed["reason"] == "Invalid session stream token"


@pytest.mark.asyncio
async def test_session_stream_websocket_requires_token(client, auth_headers, db):
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]
    websocket = FakeWebSocket("")

    await session_stream_ws(session_id, websocket, db=db)
    assert websocket.closed == {"code": 1008, "reason": "Session stream token required"}


@pytest.mark.asyncio
async def test_session_stream_websocket_rejects_token_for_different_session(client, auth_headers, db):
    first_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    second_resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    first_session = first_resp.json()
    second_session = second_resp.json()
    token = create_session_stream_token(user_id=first_session["user_id"], session_id=first_session["id"])
    websocket = FakeWebSocket(token)

    await session_stream_ws(second_session["id"], websocket, db=db)
    assert websocket.closed == {
        "code": 1008,
        "reason": "Session stream token does not match requested session",
    }


@pytest.mark.asyncio
async def test_session_stream_websocket_rejects_token_without_session_access(client, auth_headers, db):
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    session_id = resp.json()["id"]
    token = create_session_stream_token(user_id=str(uuid.uuid4()), session_id=session_id)
    websocket = FakeWebSocket(token)

    await session_stream_ws(session_id, websocket, db=db)
    assert websocket.closed == {"code": 1008, "reason": "Session not found"}


@pytest.mark.asyncio
async def test_session_stream_websocket_receives_published_events(client, auth_headers, db):
    resp = await client.post(
        "/api/v1/sessions",
        json={"agent_type": "diagnosis"},
        headers=auth_headers,
    )
    payload = resp.json()
    session_id = payload["id"]
    token = create_session_stream_token(user_id=payload["user_id"], session_id=session_id)
    websocket = FakeWebSocket(token)

    task = asyncio.create_task(session_stream_ws(session_id, websocket, db=db))

    for _ in range(20):
        if websocket.accepted and websocket.sent:
            break
        await asyncio.sleep(0.01)

    assert websocket.accepted is True
    connected = websocket.sent[0]
    assert connected["type"] == "connected"
    assert connected["sessionId"] == session_id

    await session_stream_manager.publish(
        session_id,
        "agent_message",
        {"content": "hello from ws"},
    )

    for _ in range(20):
        if len(websocket.sent) >= 2:
            break
        await asyncio.sleep(0.01)

    message = websocket.sent[1]
    assert message["type"] == "agent_message"
    assert message["sessionId"] == session_id
    assert message["content"] == "hello from ws"

    await session_stream_manager.publish(
        session_id,
        "agent_message",
        {
            "type": "wrong_type",
            "sessionId": "wrong-session",
            "content": "canonical envelope wins",
        },
    )

    for _ in range(20):
        if len(websocket.sent) >= 3:
            break
        await asyncio.sleep(0.01)

    protected_message = websocket.sent[2]
    assert protected_message["type"] == "agent_message"
    assert protected_message["sessionId"] == session_id
    assert protected_message["content"] == "canonical envelope wins"

    websocket.disconnect()
    await task
