"""Shared helpers for the test_dispatch_admission_surfaces_* modules."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project
from tests.factories import make_project

from .conftest import backup_runtime, gateway_runtime


async def _project(db: AsyncSession, *, policy: dict | None) -> Project:
    return await make_project(
        db,
        name=f"surface-{uuid.uuid4().hex[:8]}",
        config={
            **({"model_policy": policy} if policy is not None else {}),
            "data_policy": {"classification": "internal"},
        },
    )


class _ForbiddenProviderFactory:
    def __call__(self, **kwargs: Any) -> Any:
        raise AssertionError(f"a provider client must not be constructed: {sorted(kwargs)}")


async def _mixed_chain() -> list[dict[str, Any]]:
    return [gateway_runtime(), backup_runtime()]
