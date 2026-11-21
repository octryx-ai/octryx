"""Shared helpers for the test_prompt_catalog_contract_* modules."""

from __future__ import annotations

from sqlalchemy import select

from app.models import User
from tests.prompt_catalog_publish_support import publish_reviewed

KEY = "system.skill_discovery"  # standard risk, no placeholders


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _publish(db, key: str, body: str, *, scope_type: str = "global", scope_id: str | None = None) -> None:
    await publish_reviewed(db, key, body, scope_type=scope_type, scope_id=scope_id)
