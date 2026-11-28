"""Shared helpers for the test_secure_work_plan_access_* modules."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    IdentityGroup,
    Project,
    ProjectGroup,
    Role,
    User,
    UserGroup,
    UserProject,
    UserRole,
    WorkChangePlan,
    WorkChangePlanDecision,
    WorkItem,
)
from app.services.auth.tokens import hash_password


async def _role(db, name: str) -> Role:
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        role = Role(name=name)
        db.add(role)
        await db.flush()
    return role


async def _user(db, label: str, *, operator: bool = True) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{label}-{suffix}",
        email=f"{label}-{suffix}@example.test",
        password_hash=hash_password("plan-Access-Pw-123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if operator:
        db.add(UserRole(user_id=user.id, role_id=(await _role(db, "operator")).id))
    return user


async def _item_with_plan(db, owner: User, project_id: str | None) -> tuple[WorkItem, WorkChangePlan]:
    key = f"OCX-ACCESS-{uuid.uuid4().hex[:8]}"
    item = WorkItem(
        project_id=project_id,
        source_type="jira",
        source_instance="plan-access-test",
        source_key=key,
        title=f"Scoped plan {key}",
        work_state="intake",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    plan = WorkChangePlan(
        work_item_id=item.id, version=1, status="ready_for_review", title=f"{key} plan", created_by=owner.id
    )
    db.add(plan)
    await db.flush()
    return item, plan


@pytest.fixture
async def world(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    suffix = uuid.uuid4().hex[:8]
    own, foreign = Project(name=f"Plan Own {suffix}"), Project(name=f"Plan Foreign {suffix}")
    group = IdentityGroup(name=f"plan-group-{suffix}", is_active=True)
    db.add_all([own, foreign, group])
    await db.flush()
    member = await _user(db, "member")
    group_member = await _user(db, "group-member")
    outsider = await _user(db, "outsider")
    plain_member = await _user(db, "plain-member", operator=False)
    db.add_all(
        [
            UserProject(user_id=member.id, project_id=own.id),
            UserProject(user_id=plain_member.id, project_id=own.id),
            UserGroup(user_id=group_member.id, group_id=group.id),
            ProjectGroup(project_id=own.id, group_id=group.id),
        ]
    )
    own_item, own_plan = await _item_with_plan(db, admin, own.id)
    foreign_item, foreign_plan = await _item_with_plan(db, admin, foreign.id)
    null_item, null_plan = await _item_with_plan(db, admin, None)
    await db.commit()
    return {
        "admin": admin,
        "member": member,
        "group_member": group_member,
        "outsider": outsider,
        "plain_member": plain_member,
        "own_project": own,
        "own": (own_item, own_plan),
        "foreign": (foreign_item, foreign_plan),
        "null": (null_item, null_plan),
    }


async def _side_effects(db, item: WorkItem) -> tuple:
    statuses = (
        (await db.execute(select(WorkChangePlan.status).where(WorkChangePlan.work_item_id == item.id))).scalars().all()
    )
    decisions = (
        await db.execute(
            select(func.count(WorkChangePlanDecision.id)).where(WorkChangePlanDecision.work_item_id == item.id)
        )
    ).scalar_one()
    audits = (await db.execute(select(func.count(AuditLog.id)).where(AuditLog.resource_id == item.id))).scalar_one()
    return sorted(statuses), decisions, audits
