"""Shared helpers for the test_rbac_boundaries_* modules."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, User, UserProject

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


async def _make_project(db: AsyncSession, *, name: str | None = None) -> Project:
    project = Project(
        id=_uid(),
        name=name or f"test-project-{uuid.uuid4().hex[:6]}",
    )
    db.add(project)
    await db.flush()
    return project


async def _make_user(db: AsyncSession, *, username: str | None = None) -> User:

    user = User(
        id=_uid(),
        username=username or f"user_{uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:6]}@test.local",
        password_hash="x",
        auth_source="local",
    )
    db.add(user)
    await db.flush()
    return user


async def _grant_project_membership(
    db: AsyncSession, user_id: str, project_id: str, role: str = "member"
) -> None:
    membership = UserProject(
        user_id=user_id,
        project_id=project_id,
        role=role,
        granted_by=user_id,
    )
    db.add(membership)
    await db.flush()
