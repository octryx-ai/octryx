"""Shared users, roles, items, sessions, the world fixture and service spies for the test_mcp_work_grant_scope_* modules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    Project,
    Role,
    Session,
    User,
    UserProject,
    UserRole,
    WorkChangePlan,
    WorkChangePlanDecision,
    WorkItem,
    WorkItemChangeUnit,
    WorkItemWorkflowDefinition,
)
from app.services import mcp_knowledge_protocol, mcp_secure_work_tools
from app.services.auth.tokens import hash_password
from tests.mcp_native_support import session_factory

WORK_SCOPES = ["work:manage", "knowledge:read"]


# Business services each handler may reach; a refused call must never enter one of them.
SERVICE_NAMES = (
    "plan_work_item_change_units",
    "generate_change_plan",
    "decide_change_plan",
    "redeclare_work_item",
    "start_work_item_coding_agent_execution",
    "transition_work_item",
    "get_work_item_coding_observability",
    "create_platform_work_item",
    "build_work_item_context",
    "add_work_item_note",
    "link_validated_session_to_work_item",
)


async def _role(db, name: str) -> Role:
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if role is None:
        role = Role(name=name)
        db.add(role)
        await db.flush()
    return role


async def _user(db, label: str, *, operator: bool, projects: list[str]) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        username=f"{label}-{suffix}",
        email=f"{label}-{suffix}@example.test",
        password_hash=hash_password("grant-Scope-Pw-123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if operator:
        db.add(UserRole(user_id=user.id, role_id=(await _role(db, "operator")).id))
    db.add_all([UserProject(user_id=user.id, project_id=project_id) for project_id in projects])
    return user


def _item(project_id: str | None, key: str, instance: str = "grant-scope-test") -> WorkItem:
    return WorkItem(
        project_id=project_id,
        source_type="jira",
        source_instance=instance,
        source_key=key,
        title=f"Grant scope {key}",
        work_state="intake",
        sync_state="imported",
    )


def _session(user: User, project_id: str | None, client_session_id: str) -> Session:
    return Session(
        id=str(uuid.uuid4()),
        user_id=user.id,
        project_id=project_id,
        agent_type="external_agent",
        status="completed",
        metadata_={"client_session_id": client_session_id},
    )


@pytest.fixture
async def world(db, monkeypatch):
    monkeypatch.setattr(mcp_knowledge_protocol, "async_session_factory", session_factory(db))
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    suffix = uuid.uuid4().hex[:8]
    a, b = Project(name=f"Grant A {suffix}"), Project(name=f"Grant B {suffix}")
    db.add_all([a, b])
    await db.flush()
    member = await _user(db, "member", operator=True, projects=[a.id, b.id])
    plain = await _user(db, "plain", operator=False, projects=[a.id, b.id])
    other = await _user(db, "other", operator=True, projects=[a.id])
    same_key = f"SAME-{suffix}"
    items = {
        "a": _item(a.id, f"A-{suffix}"),
        "b": _item(b.id, f"B-{suffix}"),
        "null": _item(None, f"NULL-{suffix}"),
        "same_a": _item(a.id, same_key, "instance-a"),
        "same_b": _item(b.id, same_key, "instance-b"),
        "dup_a1": _item(a.id, f"DUP-{suffix}", "instance-1"),
        "dup_a2": _item(a.id, f"DUP-{suffix}", "instance-2"),
    }
    db.add_all(items.values())
    await db.flush()
    plans = {
        name: WorkChangePlan(
            work_item_id=items[name].id, version=1, status="ready_for_review", title=f"{name} plan", created_by=admin.id
        )
        for name in ("a", "b", "null")
    }
    sessions = {
        "own_a": _session(member, a.id, f"cc-a-{suffix}"),
        "own_b": _session(member, b.id, f"cc-b-{suffix}"),
        "other_a": _session(other, a.id, f"cc-x-{suffix}"),
        "dup_1": _session(member, a.id, f"cc-dup-{suffix}"),
        "dup_2": _session(member, a.id, f"cc-dup-{suffix}"),
    }
    workflows = {
        name: WorkItemWorkflowDefinition(name=f"wf-{name}-{suffix}", project_id=project_id, created_by=admin.id)
        for name, project_id in (("a", a.id), ("b", b.id), ("global", None))
    }
    db.add_all([*plans.values(), *sessions.values(), *workflows.values()])
    await db.commit()
    return SimpleNamespace(
        db=db,
        admin=admin,
        member=member,
        plain=plain,
        a=a.id,
        b=b.id,
        items=items,
        plans=plans,
        sessions=sessions,
        workflows={name: row.id for name, row in workflows.items()},
    )


@pytest.fixture
def spies(monkeypatch):
    entered: list[str] = []

    def _spy(name: str):
        async def _service(*_args, **_kwargs):
            entered.append(name)
            raise AssertionError(f"{name} entered for a refused call")

        return _service

    for name in SERVICE_NAMES:
        monkeypatch.setattr(mcp_secure_work_tools, name, _spy(name))
    return entered


async def _snapshot(db) -> tuple:
    items = (await db.execute(select(WorkItem.id, WorkItem.work_state, WorkItem.source_fields_json))).all()
    plans = (await db.execute(select(WorkChangePlan.id, WorkChangePlan.status))).all()
    sessions = (await db.execute(select(Session.id, Session.metadata_))).all()
    counts = [
        (await db.execute(select(func.count(model.id)))).scalar_one()
        for model in (WorkItem, WorkChangePlanDecision, WorkItemChangeUnit)
    ]
    business_audits = (
        await db.execute(select(func.count(AuditLog.id)).where(AuditLog.resource_type != "mcp_knowledge"))
    ).scalar_one()
    return sorted(map(tuple, items)), sorted(map(tuple, plans)), sorted(map(str, sessions)), counts, business_audits


def _error_text(result: dict) -> str:
    assert result.get("isError"), result
    return str(result.get("content"))
