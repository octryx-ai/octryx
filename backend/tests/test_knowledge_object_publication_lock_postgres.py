"""On real PostgreSQL with two real connections, transactions serialize on one object and never on another."""

from __future__ import annotations

import asyncio
import uuid

from app.services.knowledge.objects.publication_lock import lock_object_publication, serializes_object_publication
from tests.knowledge_retention_postgres_support import (
    GRANTED_ADVISORY,
    UNGRANTED_ADVISORY,
    postgres_sessions,
    requires_postgres,
    scalar,
    until,
)

# --- real PostgreSQL, two real connections ----------------------------------


@requires_postgres
async def test_two_transactions_serialize_on_one_object_and_never_on_another():
    """The boundary itself: measured in ``pg_locks``, not in elapsed time."""
    engine, factory = postgres_sessions()
    workspace_id = str(uuid.uuid4())
    key = "octryx/test/knowledge/octryx_ws_" + "0" * 32 + "/sha256/aa/bb/" + "aabb" + "c" * 60
    other_key = key[:-1] + "d"
    try:
        async with factory() as holder, factory() as rival, factory() as observer:
            assert serializes_object_publication(holder) is True
            first = await lock_object_publication(holder, project_id=workspace_id, object_key=key)
            assert first.serialized is True
            assert await scalar(observer, GRANTED_ADVISORY) >= 1

            # Another object of the same Workspace is a different key: granted immediately.
            await asyncio.wait_for(
                lock_object_publication(rival, project_id=workspace_id, object_key=other_key),
                timeout=10,
            )
            await rival.rollback()

            # The same object waits, and the wait is visible as an ungranted advisory lock.
            waiting = asyncio.create_task(
                lock_object_publication(rival, project_id=workspace_id, object_key=key)
            )
            await until(observer, UNGRANTED_ADVISORY, 1)
            assert not waiting.done()

            # Releasing the holder's transaction releases the lock; nothing unlocks by hand.
            await holder.rollback()
            granted = await asyncio.wait_for(waiting, timeout=10)
            assert granted.serialized is True
            assert await scalar(observer, UNGRANTED_ADVISORY) == 0
            await rival.rollback()
    finally:
        await engine.dispose()
