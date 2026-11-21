from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import (
    LLMCacheEntry,
    Message,
    PrefetchCacheEntry,
    Session,
    SessionToolCacheEntry,
    User,
)
from app.services.chat_rerun import prepare_chat_rerun
from app.time_utils import utc_now


@pytest.mark.asyncio
async def test_chat_rerun_clears_session_scoped_caches_but_keeps_llm_cache(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin.id, metadata_={})
    target_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="user",
        content="Original prompt",
        created_at=utc_now() - timedelta(minutes=1),
    )
    later_message = Message(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content="Stale answer",
        created_at=utc_now(),
    )
    db.add_all([session, target_message, later_message])
    db.add(
        SessionToolCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tool_name="list_failed_pods",
            params_hash="session-cache",
            result_json={"source": "session"},
            ttl_seconds=60,
            cached_at=utc_now(),
        )
    )
    db.add(
        PrefetchCacheEntry(
            id=str(uuid.uuid4()),
            session_id=session.id,
            tool_name="list_failed_pods",
            params_hash="prefetch-cache",
            params_json={"namespace": "payments"},
            result_json={"source": "prefetch"},
            created_at=utc_now(),
        )
    )
    db.add(
        LLMCacheEntry(
            id=str(uuid.uuid4()),
            prompt_hash="b" * 64,
            provider_id="provider-audit",
            model_id="model-audit",
            response_json={"content": "stable", "tool_calls": None},
            hit_count=0,
            cache_scope="default",
            expires_at=utc_now() + timedelta(minutes=30),
        )
    )
    await db.commit()

    preparation = await prepare_chat_rerun(
        db,
        session=session,
        target_message=target_message,
        prompt="Edited prompt",
    )

    assert preparation.prompt == "Edited prompt"

    remaining_session_cache = (
        (await db.execute(select(SessionToolCacheEntry).where(SessionToolCacheEntry.session_id == session.id)))
        .scalars()
        .all()
    )
    remaining_prefetch_cache = (
        (await db.execute(select(PrefetchCacheEntry).where(PrefetchCacheEntry.session_id == session.id)))
        .scalars()
        .all()
    )
    remaining_llm_cache = await db.execute(select(LLMCacheEntry).where(LLMCacheEntry.provider_id == "provider-audit"))
    remaining_llm_cache = remaining_llm_cache.scalars().all()

    assert remaining_session_cache == []
    assert remaining_prefetch_cache == []
    assert len(remaining_llm_cache) == 1
