"""20 parallel creates of a platform work item on a real, migrated PostgreSQL: all succeed with distinct keys.

Each create runs in its own session, as a request does. Without the fix every create reads the same highest key and
the unique index refuses all but one (HTTP 500).

Skipped unless ``OCTRYX_TEST_POSTGRES_URL`` names a disposable server; the scratch database is created and
dropped by the test.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.secure_work.platform_items import create_platform_work_item
from tests.alembic_model_parity_support import migrated_database, requires_postgres
from tests.model_policy_support import seed_workspace

pytestmark = requires_postgres

PARALLEL = 20


async def _round(url: str) -> list[object]:
    engine = create_async_engine(url, pool_size=PARALLEL, max_overflow=0)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            seeded = await seed_workspace(db)
            await db.commit()

        async def create(n: int) -> object:
            try:
                async with maker() as db:
                    item = await create_platform_work_item(db, current_user=seeded.author,
                                                           project_id=seeded.project.id, title=f"parallel {n}")
                    await db.commit()
                    return item.source_key
            except Exception as error:  # noqa: BLE001 - the failure is the finding
                return repr(error)[:200]

        return await asyncio.gather(*(create(n) for n in range(PARALLEL)))
    finally:
        await engine.dispose()


def test_twenty_parallel_creates_get_distinct_keys(tmp_path: Path):
    with migrated_database("postgresql", tmp_path) as database:
        keys = asyncio.run(_round(database.url))
    assert all(isinstance(key, str) and key.rsplit("-", 1)[-1].isdigit() for key in keys), keys
    assert len(set(keys)) == PARALLEL, keys
