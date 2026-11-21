"""Editing a user turn and rerunning it replaces every piece of state the later turns left behind."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.agent.engine import (
    AgentEvent,
)
from app.models import (
    Approval,
    ChangePreview,
    ContextCheckpoint,
    Message,
    PrefetchCacheEntry,
    Project,
    SessionEntity,
    SessionToolCacheEntry,
    ThreadContext,
    ToolArtifact,
    ToolCall,
    ToolResultCompressionLog,
    UsageEvent,
    User,
)
from app.services.session import turn_runner
from app.time_utils import utc_now
from tests.chat_edit_retry_support import (
    _messages,
    _rerun_session,
    _seed_stale_approval,
    _seed_stale_caches,
    _seed_stale_entities_and_compression,
    _seed_stale_tool_rows,
)
from tests.conftest import ADMIN_PASSWORD

_EDIT_RERUN_TURNS = (
    ("user", "Original question", 0),
    ("assistant", "Original answer", 5),
    ("user", "Second question", 10),
    ("assistant", "Stale second answer", 20),
)


async def _seed_edit_rerun_session(db, user_id, project_id):
    """Seeds two turns plus every kind of state the stale second answer left behind; returns
    (session, target user message, pending approval)."""
    session = _rerun_session(user_id, title="Original question", project_id=project_id)
    db.add(session)
    await db.flush()

    base_time = utc_now() - timedelta(minutes=10)
    first_user, first_assistant, target_user, stale_assistant = _messages(session.id, base_time, _EDIT_RERUN_TURNS)
    db.add_all([first_user, first_assistant, target_user, stale_assistant])
    await db.flush()

    _seed_stale_tool_rows(db, session.id, user_id, stale_assistant.id, base_time)
    approval = await _seed_stale_approval(db, session.id, user_id, stale_assistant.id, base_time)
    _seed_stale_caches(db, session.id, base_time)
    _seed_stale_entities_and_compression(db, session.id, target_user.id, stale_assistant.id, base_time)
    await db.commit()
    return session, target_user, approval


async def _session_rows(db, model, session_id):
    return (await db.execute(select(model).where(model.session_id == session_id))).scalars().all()


def _assert_edited_rerun_completed(final_payload) -> None:
    assert final_payload["selectedSession"]["status"] == "active"
    assert final_payload["selectedSession"]["runStatus"] == "completed"
    assert [row["content"] for row in final_payload["selectedMessages"]] == [
        "Original question",
        "Original answer",
        "Edited second question",
        "Fresh rerun answer",
    ]


async def _assert_later_turn_state_replaced(db, session_id, approval_id) -> None:
    remaining_tool_calls = await _session_rows(db, ToolCall, session_id)
    remaining_previews = await _session_rows(db, ChangePreview, session_id)
    remaining_thread_context = await _session_rows(db, ThreadContext, session_id)
    remaining_usage = await _session_rows(db, UsageEvent, session_id)
    remaining_artifacts = await _session_rows(db, ToolArtifact, session_id)
    remaining_cache = await _session_rows(db, SessionToolCacheEntry, session_id)
    remaining_prefetch = await _session_rows(db, PrefetchCacheEntry, session_id)
    remaining_checkpoints = await _session_rows(db, ContextCheckpoint, session_id)
    remaining_entities = await _session_rows(db, SessionEntity, session_id)
    remaining_compression_logs = await _session_rows(db, ToolResultCompressionLog, session_id)

    assert remaining_tool_calls == []
    # Approval and usage history is append-only: the replaced run's pending approval is cancelled,
    # its preview and its spend stay recorded.
    # (column select: the test session still holds the approval as it seeded it)
    approval_statuses = (
        await db.execute(select(Approval.id, Approval.status).where(Approval.session_id == session_id))
    ).all()
    assert [tuple(row) for row in approval_statuses] == [(approval_id, "cancelled")]
    assert [row.approval_id for row in remaining_previews] == [approval_id]
    assert remaining_thread_context == []
    assert [row.tokens_in for row in remaining_usage] == [111]
    assert remaining_artifacts == []
    assert remaining_cache == []
    assert remaining_prefetch == []
    assert remaining_checkpoints == []
    assert remaining_entities == []
    assert remaining_compression_logs == []


@pytest.mark.asyncio
@pytest.mark.committed_db
async def test_admin_chat_edit_and_rerun_replaces_later_turn_state(client, db, monkeypatch):
    login_resp = await client.post("/admin/login", data={"username": "admin", "password": ADMIN_PASSWORD})
    assert login_resp.status_code == 303

    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    session, target_user, approval = await _seed_edit_rerun_session(db, admin_user.id, project.id)

    async def fake_run_agent(*, session_id, user_message, db, **kwargs):
        assert session_id == session.id
        assert user_message == "Edited second question"
        content = "Fresh rerun answer"
        db.add(
            Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=content,
            )
        )
        await db.flush()
        yield AgentEvent(role="assistant", content=content)

    monkeypatch.setattr(turn_runner, "run_agent", fake_run_agent)

    rerun_resp = await client.post(
        f"/admin/chat/api/sessions/{session.id}/messages/{target_user.id}/rerun",
        json={"prompt": "Edited second question"},
    )
    assert rerun_resp.status_code == 200
    payload = rerun_resp.json()
    assert payload["selectedSession"]["status"] in {"running", "active"}
    assert payload["selectedMessages"][2]["content"] == "Edited second question"
    assert payload["selectedMessages"][-1]["content"] != "Stale second answer"

    final_payload = payload
    for _ in range(20):
        await asyncio.sleep(0.05)
        final_resp = await client.get(f"/admin/chat/api/bootstrap?session_id={session.id}")
        assert final_resp.status_code == 200
        final_payload = final_resp.json()
        if not final_payload["selectedSessionIsRunning"]:
            break

    _assert_edited_rerun_completed(final_payload)

    await db.rollback()
    await _assert_later_turn_state_replaced(db, session.id, approval.id)
