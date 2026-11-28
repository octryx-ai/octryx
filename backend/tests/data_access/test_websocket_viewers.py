from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.api.routes.channels.teams_calling import call_audio_ws
from app.api.routes.sessions._sessions_sharing_routes import session_stream_ws
from app.api.routes.sessions.canvas import canvas_ws
from app.models import ChannelConfig, Session
from app.services.auth import create_session_stream_token
from app.services.canvas import canvas_manager
from app.services.data_access import Viewer, bind_request_viewer, current_viewer, request_scope
from app.services.pr_review_bot import webhook as review_webhook
from app.services.project.private_workspace import ensure_private_workspace
from app.services.teams_calling.audio_ws_token import issue_call_audio_token, revoke_call_audio_token
from tests.api.test_session_collaboration_streams import _FakeCanvasWebSocket, _FakeWebSocket
from tests.devices.device_support import user_named
from tests.phased_workflow_fixtures import admin_user
from tests.services.channels.test_teams_call_audio_token import _AudioSocket


@pytest.fixture
async def private_session(db):
    owner = await user_named(db, f"ws-owner-{uuid.uuid4().hex[:6]}")
    workspace = (await ensure_private_workspace(db, owner)).id
    session = Session(id=str(uuid.uuid4()), user_id=owner.id, project_id=workspace, origin="chat", status="active")
    db.add(session)
    await db.commit()
    return owner, workspace, session.id


async def _fresh_request(handler, *args, **kwargs) -> None:
    with request_scope():
        await handler(*args, **kwargs)


async def test_the_session_stream_reads_as_its_tokens_person(db, private_session):
    owner, _workspace, session_id = private_session
    admin = await admin_user(db)
    own, foreign = (_FakeWebSocket(create_session_stream_token(user_id=user_id, session_id=session_id))
                    for user_id in (owner.id, admin.id))
    await _fresh_request(session_stream_ws, session_id, own, db)
    await _fresh_request(session_stream_ws, session_id, foreign, db)
    assert (own.accepted, own.closed, own.sent_messages[0]["type"]) == (True, None, "connected")
    assert foreign.accepted is False and foreign.closed is not None


async def test_the_canvas_reads_as_its_tokens_person(db, private_session):
    owner, _workspace, session_id = private_session
    admin = await admin_user(db)
    canvas = canvas_manager.get_or_create(session_id)
    own, foreign = (_FakeCanvasWebSocket(create_session_stream_token(user_id=user_id, session_id=session_id))
                    for user_id in (owner.id, admin.id))
    await _fresh_request(canvas_ws, canvas.id, own, db)
    await _fresh_request(canvas_ws, canvas.id, foreign, db)
    assert (own.accepted, own.closed) == (True, None)
    assert (foreign.accepted, foreign.closed) == (False, (1008, "Session not found"))


async def test_the_call_audio_socket_reads_as_its_channels_owner(db, private_session):
    _owner, workspace, _session_id = private_session
    channel = ChannelConfig(plugin_id="msteams", name="Calls", project_id=workspace, enabled=True,
                            config=json.dumps({"calling_enabled": True}))
    db.add(channel)
    await db.commit()
    token = issue_call_audio_token("call-private", channel_id=str(channel.id), project_id=workspace)
    socket = _AudioSocket()
    try:
        await _fresh_request(call_audio_ws, call_id="call-private", ws=socket, project_id=workspace,
                             channel_id=str(channel.id), token=token, db=db)
    finally:
        revoke_call_audio_token("call-private")
    assert (socket.accepted, socket.closed, socket.reads) == (True, None, 1)


async def test_review_work_a_webhook_leaves_running_reads_as_its_principal_after_the_answer():
    answered = asyncio.Event()
    seen: list[object] = []

    async def work() -> None:
        await answered.wait()
        seen.append(current_viewer())

    with request_scope():
        bind_request_viewer("integration-owner")
        review_webhook._spawn(work())
    answered.set()
    await asyncio.gather(*review_webhook._BACKGROUND)
    assert seen == [Viewer("integration-owner")]
