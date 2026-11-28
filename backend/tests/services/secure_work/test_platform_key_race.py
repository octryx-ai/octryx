"""A platform work item whose key a parallel create just took gets the next free key instead of a 500.
The parallel proof on PostgreSQL is tests/services/secure_work/test_platform_key_race_postgres.py."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Project
from app.services.secure_work import platform_items
from app.services.secure_work.platform_items import create_platform_work_item


@pytest.mark.asyncio
async def test_a_key_taken_meanwhile_moves_to_the_next_free_one(db, monkeypatch, auth_user):
    project = (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()
    first = await create_platform_work_item(db, current_user=auth_user, project_id=project.id, title="first")

    real = platform_items._next_platform_key
    stale = iter([first.source_key])

    async def a_stale_read_first(db_, *, prefix, above=0):
        # What a parallel create sees: the highest key before the other one committed.
        return next(stale, None) or await real(db_, prefix=prefix, above=above)

    monkeypatch.setattr(platform_items, "_next_platform_key", a_stale_read_first)
    second = await create_platform_work_item(db, current_user=auth_user, project_id=project.id, title="second")
    prefix, number = first.source_key.rsplit("-", 1)
    assert second.source_key == f"{prefix}-{int(number) + 1}"
