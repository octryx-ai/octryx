"""Shared helpers for the test_dispatch_admission_owners_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from tests.factories import make_project


class _ForbiddenProviderFactory:
    def __call__(self, **kwargs: Any) -> Any:
        raise AssertionError(f"a provider client must not be constructed: {sorted(kwargs)}")


async def _project(db: AsyncSession, *, policy: dict | None) -> Project:
    return await make_project(
        db,
        name=f"owner-{uuid.uuid4().hex[:8]}",
        config={
            **({"model_policy": policy} if policy is not None else {}),
            "data_policy": {"classification": "internal"},
        },
    )


async def _targets(provider: Any, model: Any) -> list[tuple[Any, Any]]:
    return [(provider, model)]
