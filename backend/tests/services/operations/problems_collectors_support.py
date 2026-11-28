"""Shared helpers for the test_problems_collectors_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Project, User
from app.services.problems.model import CollectContext
from app.time_utils import utc_now

NOW = utc_now()


def uid() -> str:
    return str(uuid.uuid4())


async def _setup(db) -> tuple[Project, User, CollectContext]:
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    project = Project(id=uid(), name=f"Problems {uid()[:6]}", is_active=True, config={})
    db.add(project)
    await db.flush()
    return project, admin, CollectContext(now=NOW, workspace_ids=frozenset({project.id}))


def _by_object(problems, object_id: str) -> list:
    return [item for item in problems if item.object_id == object_id]
