from __future__ import annotations

from datetime import datetime

from app.models import Session as ChatSession
from app.models import UsageEvent, User
from app.services.secure_work.coding.session_usage_report import (
    USAGE_BLOCK_HEADER,
    append_agent_usage_block_for_governed_session,
    build_agent_usage_block,
)


async def _user(db) -> User:
    user = User(username="usage-report-user", email="usage-report@example.test", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _session(db, user: User, *, governed: bool) -> ChatSession:
    metadata = (
        {"secure_work_execution": {"work_item_id": "wi-1", "verification_contract": {"commands": []}}}
        if governed
        else {}
    )
    session = ChatSession(user_id=user.id, metadata_=metadata)
    db.add(session)
    await db.flush()
    return session


def _event(session: ChatSession, user: User, *, tokens_in: int, tokens_out: int, created_at: datetime) -> UsageEvent:
    return UsageEvent(
        session_id=session.id,
        user_id=user.id,
        provider="minimax",
        model="MiniMax-M3",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost=0,
        created_at=created_at,
    )


async def test_usage_block_aggregates_session_events(db):
    user = await _user(db)
    session = await _session(db, user, governed=True)
    db.add(_event(session, user, tokens_in=1000, tokens_out=50, created_at=datetime(2026, 7, 5, 18, 53)))
    db.add(_event(session, user, tokens_in=2500, tokens_out=150, created_at=datetime(2026, 7, 5, 20, 33)))
    await db.flush()

    block = await build_agent_usage_block(db, session.id)
    assert USAGE_BLOCK_HEADER in block
    assert "minimax/MiniMax-M3" in block
    assert "LLM requests: 2" in block
    assert "3,500 in / 200 out" in block
    assert "not priced" in block
    assert "2026-07-05 18:53 - 20:33 UTC" in block


async def test_append_only_for_governed_sessions_and_idempotent(db):
    user = await _user(db)
    governed = await _session(db, user, governed=True)
    plain = await _session(db, user, governed=False)
    for session in (governed, plain):
        db.add(_event(session, user, tokens_in=10, tokens_out=5, created_at=datetime(2026, 7, 6, 9, 0)))
    await db.flush()

    body = "Delivered branch feature/x, PR #1, validation all green."
    appended = await append_agent_usage_block_for_governed_session(db, governed.id, body)
    assert appended.startswith(body)
    assert USAGE_BLOCK_HEADER in appended

    # idempotent across delivery retries
    assert await append_agent_usage_block_for_governed_session(db, governed.id, appended) == appended
    # non-governed session: untouched
    assert await append_agent_usage_block_for_governed_session(db, plain.id, body) == body
    # no db / no session id: untouched
    assert await append_agent_usage_block_for_governed_session(None, governed.id, body) == body
    assert await append_agent_usage_block_for_governed_session(db, None, body) == body


async def test_no_events_appends_nothing(db):
    user = await _user(db)
    session = await _session(db, user, governed=True)
    body = "Delivery comment."
    assert await append_agent_usage_block_for_governed_session(db, session.id, body) == body
