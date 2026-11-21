import uuid

import pytest
from sqlalchemy import select

from app.models import Message, RuntimeContextCompaction, Session, User
from app.services.context_compaction import ensure_session_context_compaction, render_context_compaction_for_prompt


@pytest.mark.asyncio
async def test_context_compaction_persists_evidence_and_avoids_duplicates(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    messages: list[Message] = []
    for index in range(14):
        role = "user" if index % 2 == 0 else "assistant"
        message = Message(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role=role,
            content=f"{role} message {index}",
            tool_calls=[
                {
                    "id": f"call-{index}",
                    "function": {"name": "knowledge_search"},
                }
            ]
            if role == "assistant"
            else None,
        )
        messages.append(message)
        db.add(message)
    await db.commit()

    compaction = await ensure_session_context_compaction(
        db,
        session_id=session.id,
        messages=messages,
        recent_window=4,
        min_source_messages=4,
    )
    assert compaction is not None
    assert compaction.source_message_count == 10
    assert compaction.recent_message_count == 4
    assert compaction.source_first_message_id == messages[0].id
    assert compaction.source_last_message_id == messages[9].id
    assert "Source messages compacted: 10" in compaction.summary_text
    assert any(ref.get("type") == "tool_call" for ref in compaction.evidence_refs_json)

    duplicate = await ensure_session_context_compaction(
        db,
        session_id=session.id,
        messages=messages,
        recent_window=4,
        min_source_messages=4,
    )
    assert duplicate is not None
    assert duplicate.id == compaction.id

    prompt = render_context_compaction_for_prompt(compaction)
    assert "Active context compaction" in prompt
    assert messages[0].id in prompt
    assert "knowledge_search" in prompt


@pytest.mark.asyncio
async def test_context_compaction_supersedes_when_source_window_moves(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    db.add(session)
    messages = [
        Message(id=str(uuid.uuid4()), session_id=session.id, role="user", content=f"request {index}")
        for index in range(14)
    ]
    db.add_all(messages)
    await db.commit()

    first = await ensure_session_context_compaction(
        db,
        session_id=session.id,
        messages=messages,
        recent_window=4,
        min_source_messages=4,
    )
    assert first is not None

    added = Message(id=str(uuid.uuid4()), session_id=session.id, role="assistant", content="continued")
    db.add(added)
    await db.commit()
    second = await ensure_session_context_compaction(
        db,
        session_id=session.id,
        messages=[*messages, added],
        recent_window=4,
        min_source_messages=4,
    )
    assert second is not None
    assert second.id != first.id
    assert second.compaction_index == first.compaction_index + 1

    rows = (
        (await db.execute(select(RuntimeContextCompaction).where(RuntimeContextCompaction.session_id == session.id)))
        .scalars()
        .all()
    )
    statuses = {row.id: row.status for row in rows}
    assert statuses[first.id] == "superseded"
    assert statuses[second.id] == "active"
