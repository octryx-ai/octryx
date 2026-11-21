"""Shared helpers for the test_task_schedule_validation_* modules."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Project, Task, User


def _detail(exc: pytest.ExceptionInfo[HTTPException]) -> dict:
    assert exc.value.status_code == 422
    return exc.value.detail


async def _admin(db: AsyncSession) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _project(db: AsyncSession) -> Project:
    return (await db.execute(select(Project).where(Project.name == "acme-orders"))).scalar_one()


async def _task_count(db: AsyncSession, name: str) -> int:
    return (await db.execute(select(func.count()).select_from(Task).where(Task.name == name))).scalar_one()
