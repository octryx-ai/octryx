"""Test helpers for System prompt texts (A7): every key publishes through the four-eyes review."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Approval, Role, User, UserRole
from app.services.prompt_catalog import lifecycle


async def admin_user(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def second_admin(db) -> User:
    reviewer = User(username=f"reviewer-{uuid.uuid4().hex[:6]}", email=f"r-{uuid.uuid4().hex[:6]}@x.test",
                    password_hash="x")
    db.add(reviewer)
    await db.flush()
    admin_role = (await db.execute(select(Role).where(Role.name == "admin"))).scalar_one()
    db.add(UserRole(user_id=reviewer.id, role_id=admin_role.id))
    await db.flush()
    return reviewer


async def publish_reviewed(db, key: str, body: str, *, scope_type: str = "global", scope_id: str | None = None):
    admin = await admin_user(db)
    _template, version = await lifecycle.create_draft(
        db, key=key, scope_type=scope_type, scope_id=scope_id, body=body, change_note="test", user=admin
    )
    submitted = await lifecycle.submit_for_review(db, version_id=version.id, user=admin)
    approval = await db.get(Approval, submitted.approval_id)
    approval.status, approval.approved_by = "approved", (await second_admin(db)).id
    published, _gate = await lifecycle.publish(db, version_id=version.id, user=admin, approval_id=approval.id)
    return published
