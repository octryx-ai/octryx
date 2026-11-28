"""20 parallel requests with one API key on a real, migrated PostgreSQL: none waits on the key's row."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import APIKey
from app.services.api_key import service
from app.services.api_key.service import authenticate_api_key
from tests.alembic_model_parity_support import migrated_database, requires_postgres
from tests.support.model_policy_support import seed_workspace

pytestmark = requires_postgres

PARALLEL = 20
REQUEST_SECONDS = 0.5


async def _round(url: str) -> tuple[list[object], float, object]:
    engine = create_async_engine(url, pool_size=PARALLEL, max_overflow=0)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = (await seed_workspace(db)).author
            raw, prefix = service.generate_api_key_value()
            entry = APIKey(user_id=user.id, name="ci", key_hash=service._hash_api_key(raw), key_prefix=prefix,
                           scopes=[])
            db.add(entry)
            await db.commit()
            key_id = entry.id

        async def request() -> object:
            try:
                async with maker() as db:
                    await db.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    await authenticate_api_key(db, raw)
                    await asyncio.sleep(REQUEST_SECONDS)  # the rest of the request, transaction still open
                    await db.commit()
                return 200
            except Exception as error:  # noqa: BLE001 - the failure is the finding
                return repr(error)[:200]

        started = time.monotonic()
        answers = await asyncio.gather(*(request() for _ in range(PARALLEL)))
        elapsed = time.monotonic() - started
        async with maker() as db:
            stored = (await db.execute(select(APIKey.last_used_at).where(APIKey.id == key_id))).scalar_one()
        return answers, elapsed, stored
    finally:
        await engine.dispose()


def test_twenty_parallel_requests_with_one_key_never_wait(tmp_path: Path):
    with migrated_database("postgresql", tmp_path) as database:
        answers, elapsed, stored = asyncio.run(_round(database.url))
    assert answers == [200] * PARALLEL, answers
    assert elapsed < REQUEST_SECONDS * 4, f"requests ran one after another: {elapsed:.2f} s"
    assert stored is not None
