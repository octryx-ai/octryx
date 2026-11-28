"""Contract: the Teams call audio WebSocket requires its call's single-use token."""

from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.api.routes.channels.teams_calling import call_audio_ws
from app.models import ChannelConfig, Project
from app.services.teams_calling import audio_ws_token
from app.services.teams_calling.audio_ws_token import issue_call_audio_token


class _AudioSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed: tuple[int, str | None] | None = None
        self.reads = 0

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        self.closed = (code, reason)

    async def receive_bytes(self) -> bytes:
        self.reads += 1
        raise WebSocketDisconnect()

    async def send_bytes(self, data: bytes) -> None:
        raise AssertionError("nothing is sent in these tests")


async def _channel(db) -> ChannelConfig:
    project = (await db.execute(Project.__table__.select().limit(1))).first()
    channel = ChannelConfig(
        plugin_id="msteams",
        name="Teams Calling",
        project_id=str(project[0]),
        enabled=True,
        config=json.dumps({"calling_enabled": True}),
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def _connect(db, channel: ChannelConfig, call_id: str, token: str, *, channel_id: str | None = None) -> _AudioSocket:
    socket = _AudioSocket()
    await call_audio_ws(
        call_id=call_id,
        ws=socket,
        project_id=str(channel.project_id),
        channel_id=channel_id or str(channel.id),
        token=token,
        db=db,
    )
    return socket


def _refused(socket: _AudioSocket, state: str) -> bool:
    return socket.closed == (1008, state) and not socket.accepted and socket.reads == 0


@pytest.mark.asyncio
async def test_the_audio_websocket_refuses_every_connect_without_its_calls_unused_token(db, monkeypatch):
    channel = await _channel(db)
    token_a = issue_call_audio_token("call-a", channel_id=str(channel.id), project_id=str(channel.project_id))
    token_b = issue_call_audio_token("call-b", channel_id=str(channel.id), project_id=str(channel.project_id))

    assert _refused(await _connect(db, channel, "call-a", ""), "call_audio_token_missing")
    assert _refused(await _connect(db, channel, "call-a", "not-the-token"), "call_audio_token_invalid")
    assert _refused(await _connect(db, channel, "call-a", token_b), "call_audio_token_invalid")
    assert _refused(await _connect(db, channel, "call-a", token_a, channel_id="424242"), "call_audio_token_invalid")

    accepted = await _connect(db, channel, "call-a", token_a)
    assert accepted.accepted and accepted.closed is None and accepted.reads == 1
    assert _refused(await _connect(db, channel, "call-a", token_a), "call_audio_token_invalid")

    monkeypatch.setattr(audio_ws_token, "TOKEN_TTL_SECONDS", -1.0)
    token_c = issue_call_audio_token("call-c", channel_id=str(channel.id), project_id=str(channel.project_id))
    assert _refused(await _connect(db, channel, "call-c", token_c), "call_audio_token_invalid")
