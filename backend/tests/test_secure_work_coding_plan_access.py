"""Contract: Coding reads of Change Plan evidence follow the owning Work Item's workspace.

- ``GET /coding-sessions`` scopes the candidate SQL itself (before the limit and the count): a
  member or group member sees only their workspaces' items and plans, an admin sees every item
  including workspace-less ones, anyone else sees nothing;
- the coding audit report, audit events and quality-gate evaluation keep the operator role check
  and refuse a foreign or workspace-less item before the service runs, so a denial writes no audit
  event, gate evaluation or AuditLog row.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine

from app.api.routes import secure_work_coding_evidence as secure_work_routes
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
    WorkCodingAuditEvent,
    WorkItem,
)
from app.services.auth.tokens import create_access_token, hash_password
from app.services.secure_work.coding.coding_sessions import list_coding_session_candidates
from app.time_utils import utc_now

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/secure-work"


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
        password_hash=hash_password("coding-Access-Pw-123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if operator:
        db.add(UserRole(user_id=user.id, role_id=(await _role(db, "operator")).id))
    return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _item_with_plan(db, owner: User, project_id: str | None, *, age_minutes: int = 0) -> tuple[str, str]:
    key = f"OCX-CODING-{uuid.uuid4().hex[:8]}"
    item = WorkItem(
        project_id=project_id,
        source_type="jira",
        source_instance="coding-access-test",
        source_key=key,
        title=f"Coding evidence {key}",
        work_state="intake",
        sync_state="imported",
        last_source_updated_at=utc_now() + timedelta(days=3650) - timedelta(minutes=age_minutes),
    )
    db.add(item)
    await db.flush()
    plan = WorkChangePlan(
        work_item_id=item.id, version=1, status="ready_for_review", title=f"{key} plan", created_by=owner.id
    )
    db.add(plan)
    await db.flush()
    return item.id, plan.id


@pytest.fixture
async def world(db):
    admin = (await db.execute(select(User).where(User.username == "admin"))).scalar_one()
    suffix = uuid.uuid4().hex[:8]
    own, foreign = Project(name=f"Coding Own {suffix}"), Project(name=f"Coding Foreign {suffix}")
    group = IdentityGroup(name=f"coding-group-{suffix}", is_active=True)
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
    # The foreign and workspace-less items are the newest, so an unscoped limit would pick them first.
    world = {
        "admin": admin,
        "member": member,
        "group_member": group_member,
        "outsider": outsider,
        "plain_member": plain_member,
        "own_project_id": own.id,
        "own": [await _item_with_plan(db, admin, own.id, age_minutes=10 + n) for n in range(2)],
        "foreign": await _item_with_plan(db, admin, foreign.id, age_minutes=1),
        "null": await _item_with_plan(db, admin, None, age_minutes=0),
    }
    await db.commit()
    return world


async def _writes(db, item_id: str) -> tuple[int, int]:
    """Coding audit events and AuditLog rows for one Work Item, read through the request's session."""
    events = (
        await db.execute(
            select(func.count(WorkCodingAuditEvent.id)).where(WorkCodingAuditEvent.work_item_id == item_id)
        )
    ).scalar_one()
    audits = (await db.execute(select(func.count(AuditLog.id)).where(AuditLog.resource_id == item_id))).scalar_one()
    return events, audits


def _candidate_ids(payload: dict) -> tuple[list[str], set[str]]:
    items = payload["items"]
    item_ids = [row["work_item"]["id"] for row in items]
    plan_ids = {plan["id"] for row in items for plan in row["change_plans"]}
    return item_ids, plan_ids


async def test_coding_candidates_are_scoped_before_limit_and_count(client, world):
    own_items = {item_id for item_id, _ in world["own"]}
    own_plans = {plan_id for _, plan_id in world["own"]}
    hidden_items = {world["foreign"][0], world["null"][0]}
    hidden_plans = {world["foreign"][1], world["null"][1]}

    for user in (world["member"], world["group_member"]):
        response = await client.get(f"{BASE}/coding-sessions?limit=5000", headers=_auth(user))
        assert response.status_code == 200, response.text
        payload = response.json()
        item_ids, plan_ids = _candidate_ids(payload)
        assert set(item_ids) == own_items and plan_ids == own_plans
        assert payload["count"] == len(item_ids) == 2 and payload["limit"] == 5000

        # The newest items are foreign/workspace-less: the limit applies after the scope.
        limited = (await client.get(f"{BASE}/coding-sessions?limit=1", headers=_auth(user))).json()
        assert limited["count"] == 1 and set(_candidate_ids(limited)[0]) <= own_items

    outsider = (await client.get(f"{BASE}/coding-sessions?limit=5000", headers=_auth(world["outsider"]))).json()
    assert outsider == {"items": [], "count": 0, "limit": 5000}

    admin = (await client.get(f"{BASE}/coding-sessions?limit=5000", headers=_auth(world["admin"]))).json()
    admin_items, admin_plans = _candidate_ids(admin)
    assert own_items | hidden_items <= set(admin_items) and own_plans | hidden_plans <= admin_plans
    assert admin["count"] == len(admin_items)
    assert admin_items[:2] == [world["null"][0], world["foreign"][0]]

    plain = await client.get(f"{BASE}/coding-sessions", headers=_auth(world["plain_member"]))
    assert plain.status_code == 403 and "operation role" in plain.json()["detail"]


async def test_coding_candidate_query_count_is_bounded(db, world):
    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        # Only reads: the transactional test harness adds SAVEPOINT statements of its own.
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    async def _queries(scope: set[str]) -> int:
        statements.clear()
        event.listen(Engine, "before_cursor_execute", _count)
        try:
            await list_coding_session_candidates(db, project_scope=scope, limit=5000)
        finally:
            event.remove(Engine, "before_cursor_execute", _count)
        return len(statements)

    scope = {world["own_project_id"]}
    with_two = await _queries(scope)
    # Items, plans, change units, state events, agent-session audit events: one batch each; plus the
    # reviewer summary: review events, reviewer overrides and the engineering-profile directory
    # (a users batch is added only when a review actor or a named reviewer needs resolving).
    assert with_two == 8
    for _ in range(4):
        await _item_with_plan(db, world["admin"], world["own_project_id"])
    await db.flush()
    assert await _queries(scope) == with_two
    assert await _queries(set()) == 0


async def test_coding_audit_entries_deny_outside_scope_before_any_write(client, db, world, monkeypatch):
    entered: list[str] = []

    def _probe(name: str):
        async def _service(*_args, **_kwargs):
            entered.append(name)
            raise AssertionError(f"{name} must not run for a denied request")

        return _service

    for name in ("get_coding_audit_report", "create_coding_audit_event", "evaluate_coding_quality_gates"):
        monkeypatch.setattr(secure_work_routes, name, _probe(name))

    denied = [(world["outsider"], scope) for scope in ("own", "foreign", "null")]
    denied += [(world["member"], "foreign"), (world["group_member"], "null")]
    for user, scope in denied:
        item_id = world[scope][0][0] if scope == "own" else world[scope][0]
        before = await _writes(db, item_id)
        responses = [
            await client.get(f"{BASE}/work-items/{item_id}/coding-audit", headers=_auth(user)),
            await client.post(
                f"{BASE}/work-items/{item_id}/coding-audit/events",
                headers=_auth(user),
                json={"event_type": "manual_note", "title": "denied probe"},
            ),
            await client.post(
                f"{BASE}/work-items/{item_id}/coding-quality-gates/evaluate", headers=_auth(user), json={}
            ),
        ]
        expected = 403 if scope == "null" else 404  # another Workspace's item answers like a missing one
        assert [r.status_code for r in responses] == [expected] * 3, (scope, [r.text for r in responses])
        assert await _writes(db, item_id) == before
    assert entered == []

    own_item = world["own"][0][0]
    for response in (
        await client.get(f"{BASE}/work-items/{own_item}/coding-audit", headers=_auth(world["plain_member"])),
        await client.post(
            f"{BASE}/work-items/{own_item}/coding-quality-gates/evaluate", headers=_auth(world["plain_member"]), json={}
        ),
    ):
        assert response.status_code == 403 and "operation role" in response.json()["detail"]
    missing = str(uuid.uuid4())
    assert (
        await client.get(f"{BASE}/work-items/{missing}/coding-audit", headers=_auth(world["member"]))
    ).status_code == 404


async def test_coding_audit_entries_allow_member_group_and_admin(client, db, world):
    own_item = world["own"][0][0]
    report = await client.get(f"{BASE}/work-items/{own_item}/coding-audit", headers=_auth(world["member"]))
    assert report.status_code == 200, report.text
    assert report.json()["evidence"]["change_plan_count"] == 1

    events_before, audits_before = await _writes(db, own_item)
    created = await client.post(
        f"{BASE}/work-items/{own_item}/coding-audit/events",
        headers=_auth(world["group_member"]),
        json={"event_type": "manual_note", "title": "Reviewed locally"},
    )
    assert created.status_code == 200, created.text
    gates = await client.post(
        f"{BASE}/work-items/{own_item}/coding-quality-gates/evaluate", headers=_auth(world["member"]), json={}
    )
    assert gates.status_code == 200, gates.text
    events_after, audits_after = await _writes(db, own_item)
    assert events_after == events_before + 2 and audits_after > audits_before

    for item_id in (world["foreign"][0], world["null"][0]):
        admin_report = await client.get(f"{BASE}/work-items/{item_id}/coding-audit", headers=_auth(world["admin"]))
        assert admin_report.status_code == 200 and admin_report.json()["work_item_id"] == item_id
        admin_gates = await client.post(
            f"{BASE}/work-items/{item_id}/coding-quality-gates/evaluate", headers=_auth(world["admin"]), json={}
        )
        assert admin_gates.status_code == 200, admin_gates.text
