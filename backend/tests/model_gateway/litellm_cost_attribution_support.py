"""Shared helpers for the test_litellm_cost_attribution_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Session, UsageEvent, User


async def _session_for(db) -> tuple[User, Session]:
    admin_user = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    session = Session(id=str(uuid.uuid4()), user_id=admin_user.id, status="active")
    db.add(session)
    await db.commit()
    return admin_user, session


async def _usage_events(db, session_id: str) -> list[UsageEvent]:
    return list((await db.execute(select(UsageEvent).where(UsageEvent.session_id == session_id))).scalars().all())
