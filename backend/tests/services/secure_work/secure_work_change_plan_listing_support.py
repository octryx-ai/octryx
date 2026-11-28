"""Shared helpers for the test_secure_work_change_plan_listing_* modules."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api.routes.secure_work.secure_work_change_plans import router
from app.db import get_db
from app.models import Project, Role, User, UserProject, UserRole, WorkChangePlan, WorkItem
from app.services.auth import get_current_user
from tests.factories import make_project

BASE = datetime(2026, 10, 1, 12, 0, 0)


URL = "/api/v1/secure-work/change-plans"


@pytest_asyncio.fixture
async def plan_api(db):
    app = FastAPI()
    app.include_router(router)
    state: dict[str, User | None] = {"user": None}

    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://plans.test") as client:
        yield client, state


async def _role(db, name: str) -> Role:
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        role = Role(name=name, description=name)
        db.add(role)
        await db.flush()
    return role


async def _user(db, username: str, *, roles: tuple[str, ...] = ("operation",), projects: tuple[str, ...] = ()) -> User:
    user = User(
        username=username,
        email=f"{username}@example.test",
        password_hash="unused",
        display_name=username.replace("-", " ").title(),
        account_type="human",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    for name in roles:
        db.add(UserRole(user_id=user.id, role_id=(await _role(db, name)).id))
    for project_id in projects:
        db.add(UserProject(user_id=user.id, project_id=project_id, role="member"))
    await db.flush()
    return user


async def _admin(db) -> User:
    return (await db.execute(select(User).where(User.username == "admin"))).scalar_one()


async def _project(db, name: str) -> Project:
    return await make_project(db, name=name)


async def _item(db, key: str, project_id: str | None) -> WorkItem:
    item = WorkItem(
        source_type="jira",
        source_instance="plan-listing-test",
        source_key=key,
        source_project_key="OCX",
        source_url=f"https://jira.example.test/browse/{key}",
        title=f"Item {key}",
        description=f"Full description of {key}",
        labels_json=["runtime"],
        project_id=project_id,
        work_state="planning",
    )
    db.add(item)
    await db.flush()
    return item


async def _plan(db, item: WorkItem, creator: User, *, version: int, status: str, minutes: int, **extra) -> WorkChangePlan:
    stamp = BASE + timedelta(minutes=minutes)
    plan = WorkChangePlan(
        work_item_id=item.id,
        version=version,
        status=status,
        title=f"{item.source_key} plan v{version}",
        created_by=creator.id,
        created_at=stamp,
        updated_at=stamp,
        open_questions_json=extra.pop("open_questions", []),
        acceptance_criteria_json=extra.pop("acceptance_criteria", []),
        change_units_json=extra.pop("change_units", []),
        evidence_json=extra.pop("evidence", {}),
        **extra,
    )
    db.add(plan)
    await db.flush()
    return plan
