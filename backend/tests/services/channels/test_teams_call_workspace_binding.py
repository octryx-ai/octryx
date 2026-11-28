from __future__ import annotations

import json
import uuid

import pytest

from app.api.routes.channels.teams_calling import call_audio_ws
from app.models import ChannelConfig
from app.services.project.private_workspace import ensure_private_workspace
from app.services.teams_calling.audio_ws_token import issue_call_audio_token, revoke_call_audio_token
from tests.devices.device_support import user_named
from tests.knowledge_evidence_seed_support import seed_workspace
from tests.services.channels.test_teams_call_audio_token import _AudioSocket

pytestmark = pytest.mark.asyncio


async def _bound_channel(db) -> ChannelConfig:
    channel = ChannelConfig(plugin_id="msteams", name="Calls", project_id=await seed_workspace(db), enabled=True,
                            config=json.dumps({"calling_enabled": True, "calling_public_ws_url": "wss://calls.example"}))
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def _other_workspaces(db) -> dict[str, str]:
    owner = await user_named(db, f"call-owner-{uuid.uuid4().hex[:6]}")
    private = await ensure_private_workspace(db, owner)
    workspaces = {"private": private.id, "shared": await seed_workspace(db), "unknown": str(uuid.uuid4())}
    await db.commit()
    return workspaces


async def test_the_audio_websocket_refuses_a_token_presented_for_another_workspace(db):
    channel, others = await _bound_channel(db), await _other_workspaces(db)
    token = issue_call_audio_token("call-ws", channel_id=str(channel.id), project_id=channel.project_id)
    socket = _AudioSocket()
    await call_audio_ws(call_id="call-ws", ws=socket, project_id=others["shared"], channel_id=str(channel.id),
                        token=token, db=db)
    assert socket.closed == (1008, "call_audio_token_invalid") and not socket.accepted


async def test_a_channel_moved_to_another_workspace_refuses_an_old_token_like_an_unknown_channel(db):
    channel, others = await _bound_channel(db), await _other_workspaces(db)
    bound_workspace = channel.project_id
    calls = {"moved": ("call-moved", str(channel.id)), "unknown": ("call-unknown", str(channel.id + 1000))}
    tokens = {kind: issue_call_audio_token(call_id, channel_id=channel_id, project_id=bound_workspace)
              for kind, (call_id, channel_id) in calls.items()}
    channel.project_id = others["private"]
    await db.commit()
    sockets = {kind: _AudioSocket() for kind in calls}
    try:
        for kind, (call_id, channel_id) in calls.items():
            await call_audio_ws(call_id=call_id, ws=sockets[kind], project_id=bound_workspace, channel_id=channel_id,
                                token=tokens[kind], db=db)
    finally:
        for call_id, _channel_id in calls.values():
            revoke_call_audio_token(call_id)
    assert sockets["moved"].closed == sockets["unknown"].closed == (1008, "Channel not found")
    assert not sockets["moved"].accepted
