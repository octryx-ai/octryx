"""last_used_at never holds the key's row for the request: written at most once per resolution, skipped when locked."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql

from app.db.touch import DEFAULT_RESOLUTION, touch_if_stale
from app.models import APIKey, User
from app.services.api_key import service
from app.services.api_key.service import authenticate_api_key
from app.time_utils import utc_now


async def _key(db) -> tuple[str, APIKey]:
    user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    raw, prefix = service.generate_api_key_value()
    entry = APIKey(user_id=user.id, name="parallel", key_hash=service._hash_api_key(raw), key_prefix=prefix, scopes=[])
    db.add(entry)
    await db.commit()
    return raw, entry


async def _stored(db, key_id: str):
    return (await db.execute(select(APIKey.last_used_at).where(APIKey.id == key_id))).scalar_one()


@pytest.mark.asyncio
async def test_first_use_is_recorded_and_a_recent_one_is_not_rewritten(db):
    raw, entry = await _key(db)
    await authenticate_api_key(db, raw)
    first = await _stored(db, entry.id)
    assert first is not None

    db.expire_all()
    await authenticate_api_key(db, raw)
    assert await _stored(db, entry.id) == first


@pytest.mark.asyncio
async def test_a_use_older_than_the_resolution_is_refreshed(db):
    raw, entry = await _key(db)
    old = utc_now() - DEFAULT_RESOLUTION - timedelta(seconds=5)
    await db.execute(update(APIKey).where(APIKey.id == entry.id).values(last_used_at=old))
    await db.commit()
    db.expire_all()
    await authenticate_api_key(db, raw)
    assert await _stored(db, entry.id) > old


@pytest.mark.asyncio
async def test_the_write_skips_a_locked_row_instead_of_waiting(db):
    _, entry = await _key(db)
    statements: list[str] = []

    class Recorder:
        def __init__(self, inner):
            self.inner = inner

        async def execute(self, statement, *args, **kwargs):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return await self.inner.execute(statement, *args, **kwargs)

    assert await touch_if_stale(Recorder(db), APIKey, entry.id, None)
    assert len(statements) == 1 and "FOR UPDATE SKIP LOCKED" in statements[0]
