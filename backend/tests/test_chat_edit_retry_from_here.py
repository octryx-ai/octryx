"""Retry from here on an assistant message, tool call, approval or change preview reruns the preceding user turn."""

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import Approval, ChangePreview, Message, ToolCall, User
from app.services.session import turn_runner
from app.time_utils import utc_now
from tests.chat_edit_retry_support import _messages, _rerun_session
from tests.conftest import ADMIN_PASSWORD


def _retry_turns(prompt, answer, *, with_later_turn=True):
    turns = [("user", prompt, 0), ("assistant", answer, 1)]
    if with_later_turn:
        turns += [("user", "Later question", 2), ("assistant", "Later answer", 3)]
    return turns


async def _seed_retry_session(db, user_id, *, title, turns, status="active"):
    """Seeds a session with the given turns (two minutes ago) and returns it with its messages."""
    session = _rerun_session(user_id, title=title, status=status)
    db.add(session)
    await db.flush()
    messages = _messages(session.id, utc_now() - timedelta(minutes=2), turns)
    db.add_all(messages)
    await db.flush()
    return session, messages


async def _seed_pending_approval(db, session_id, user_id, action) -> Approval:
    approval = Approval(
        id=str(uuid.uuid4()),
        session_id=session_id,
        requested_by=user_id,
        action=action,
        status="pending",
    )
    db.add(approval)
    await db.flush()
    return approval


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_assistant_retry_from_here_reruns_preceding_user_turn(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session, (_first_user, assistant, *_later) = await _seed_retry_session(
        db,
        admin_user.id,
        title="Assistant rerun",
        turns=_retry_turns("Original retry prompt", "Original assistant answer"),
    )
    await db.commit()

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Original retry prompt"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Assistant rerun fresh answer",
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content="Assistant rerun fresh answer")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    rerun_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/messages/{assistant.id}/rerun",
        json={"prompt": "Original retry prompt"},
    )
    assert rerun_resp.status_code == 200

    final_payload = rerun_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert [row["content"] for row in final_payload["selectedMessages"]] == [
        "Original retry prompt",
        "Assistant rerun fresh answer",
    ]
    assert final_payload["selectedSession"]["runStatus"] == "completed"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_tool_call_retry_from_here_reruns_preceding_user_turn(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session, (_first_user, assistant, *_later) = await _seed_retry_session(
        db,
        admin_user.id,
        title="Tool rerun",
        turns=_retry_turns("Original tool retry prompt", "Collecting data"),
    )
    tool_call = ToolCall(
        id=str(uuid.uuid4()),
        session_id=session.id,
        message_id=assistant.id,
        tool_name="search_confluence",
        parameters={"query": "report-builder"},
        result={"items": [{"title": "report-builder"}]},
    )
    db.add(tool_call)
    await db.commit()

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Original tool retry prompt"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Tool rerun fresh answer",
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content="Tool rerun fresh answer")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    rerun_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/tool-calls/{tool_call.id}/rerun",
        json={"prompt": "Original tool retry prompt"},
    )
    assert rerun_resp.status_code == 200

    final_payload = rerun_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert [row["content"] for row in final_payload["selectedMessages"]] == [
        "Original tool retry prompt",
        "Tool rerun fresh answer",
    ]
    assert final_payload["selectedSession"]["runStatus"] == "completed"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_approval_retry_from_here_reruns_preceding_user_turn(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session, _messages_seeded = await _seed_retry_session(
        db,
        admin_user.id,
        title="Approval rerun",
        status="pending_approval",
        turns=_retry_turns("Original approval retry prompt", "Waiting for approval", with_later_turn=False),
    )
    approval = await _seed_pending_approval(db, session.id, admin_user.id, "Run risky command")
    await db.commit()

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Original approval retry prompt"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Approval rerun fresh answer",
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content="Approval rerun fresh answer")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    rerun_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/approvals/{approval.id}/rerun",
        json={"prompt": "Original approval retry prompt"},
    )
    assert rerun_resp.status_code == 200

    final_payload = rerun_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert [row["content"] for row in final_payload["selectedMessages"]] == [
        "Original approval retry prompt",
        "Approval rerun fresh answer",
    ]
    assert final_payload["selectedSession"]["runStatus"] == "completed"


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_change_preview_retry_from_here_reruns_preceding_user_turn(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session, _messages_seeded = await _seed_retry_session(
        db,
        admin_user.id,
        title="Change preview rerun",
        status="pending_approval",
        turns=_retry_turns("Original change preview retry prompt", "Preview available", with_later_turn=False),
    )
    approval = await _seed_pending_approval(db, session.id, admin_user.id, "Write config file")
    preview = ChangePreview(
        id=str(uuid.uuid4()),
        session_id=session.id,
        approval_id=approval.id,
        tool_name="bash",
        request_fingerprint="preview-rerun",
        preview_json=json.dumps({"summary": "Preview rerun"}),
    )
    db.add(preview)
    await db.commit()

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Original change preview retry prompt"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content="Change preview rerun fresh answer",
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content="Change preview rerun fresh answer")

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    rerun_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/change-previews/{preview.id}/rerun",
        json={"prompt": "Original change preview retry prompt"},
    )
    assert rerun_resp.status_code == 200

    final_payload = rerun_resp.json()
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    assert [row["content"] for row in final_payload["selectedMessages"]] == [
        "Original change preview retry prompt",
        "Change preview rerun fresh answer",
    ]
    assert final_payload["selectedSession"]["runStatus"] == "completed"
