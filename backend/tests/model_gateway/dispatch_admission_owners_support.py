"""Shared helpers for the test_dispatch_admission_owners_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project


class _ForbiddenProviderFactory:
    """Any construction at all is a failed zero-dispatch guarantee."""

    def __call__(self, **kwargs: Any) -> Any:
        raise AssertionError(f"a provider client must not be constructed: {sorted(kwargs)}")


async def _project(db: AsyncSession, *, policy: dict | None) -> Project:
    project = Project(
        id=str(uuid.uuid4()),
        name=f"owner-{uuid.uuid4().hex[:8]}",
        config={
            **({"model_policy": policy} if policy is not None else {}),
            "data_policy": {"classification": "internal"},
        },
        is_active=True,
    )
    db.add(project)
    await db.flush()
    return project


async def _targets(provider: Any, model: Any) -> list[tuple[Any, Any]]:
    return [(provider, model)]
