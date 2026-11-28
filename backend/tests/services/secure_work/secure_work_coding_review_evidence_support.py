"""Shared world, reviewer and decision helpers for the explicit Coding reviewer decision tests."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import (
    Project,
    Role,
    User,
    UserProject,
    UserRole,
    WorkChangePlan,
    WorkCodingReviewEvent,
    WorkItem,
    WorkItemChangeUnit,
)
from app.services.auth.tokens import create_access_token, hash_password

BASE = "/api/v1/secure-work"


# Placeholder for "the unit state the page displays"; `_post` resolves it from the API like the UI.
DISPLAYED_UNIT_STATE = "__displayed_unit_state__"


async def _user(db, label: str, *, display_name: str | None = None) -> User:
    role = (await db.execute(select(Role).where(Role.name == "operator"))).scalar_one_or_none()
    if role is None:
        role = Role(name="operator")
        db.add(role)
        await db.flush()
    suffix = uuid.uuid4().hex[:6]
    user = User(
        username=f"{label}-{suffix}", email=f"{label}-{suffix}@example.test", display_name=display_name or label.title(),
        password_hash=hash_password("review-Decision-Pw-123"), is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    await db.flush()
    return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _world(db, *, reviewers=None, units=1, plan_status="approved", project_id=None, members=()):
    admin_id = (await db.execute(select(User.id).where(User.username == "admin"))).scalar_one()
    if project_id is None:
        # Reviewers reach the item through its workspace (the routes are workspace-scoped).
        project = Project(name=f"Review {uuid.uuid4().hex[:8]}")
        db.add(project)
        await db.flush()
        project_id = project.id
        db.add_all([UserProject(user_id=member.id, project_id=project_id) for member in members])
    item = WorkItem(
        project_id=project_id, source_type="jira", source_instance="review-decision-test",
        source_key=f"OCX-1131-{uuid.uuid4().hex[:6]}", title="Review decisions", work_state="in_progress",
        sync_state="imported",
    )
    db.add(item)
    await db.flush()
    unit_rows = []
    for index in range(units):
        unit = WorkItemChangeUnit(
            work_item_id=item.id, repository_name=f"repo-{index}", branch_name=f"feature/{index}",
            reviewer_policy_json={"required_reviewers": list(reviewers or [])}, created_by=admin_id,
        )
        db.add(unit)
        unit_rows.append(unit)
    plan = WorkChangePlan(work_item_id=item.id, version=1, status=plan_status, title="Plan v1", created_by=admin_id)
    db.add(plan)
    await db.commit()
    return item, plan, unit_rows


def _decision(plan, unit=None, decision="approved", **overrides):
    payload = {
        "event_type": "review_decision",
        "decision": decision,
        "change_plan_id": plan.id,
        "expected_plan_version": plan.version,
        "body": "",
    }
    if unit is not None:
        payload["change_unit_id"] = unit.id
        # The unit state the reviewer sees; resolved from the API in `_post` (an explicit override wins).
        payload["expected_change_unit_marker"] = DISPLAYED_UNIT_STATE
    payload.update(overrides)
    return payload


async def _post(client, headers, item, payload):
    if payload.get("expected_change_unit_marker") == DISPLAYED_UNIT_STATE:
        # Read the unit list as the page does: its serialized updated_at is the displayed marker.
        listed = await client.get(f"{BASE}/work-items/{item.id}/change-units", headers=headers)
        if listed.status_code == 200:
            marker = next((row["updated_at"] for row in listed.json()["items"] if row["id"] == payload["change_unit_id"]),
                          None)
            payload = {**payload, "expected_change_unit_marker": marker}
    return await client.post(f"{BASE}/work-items/{item.id}/coding-review-events", headers=headers, json=payload)


async def _gate(client, headers, item):
    response = await client.get(f"{BASE}/work-items/{item.id}/coding-audit", headers=headers)
    assert response.status_code == 200, response.text
    report = response.json()
    gate = next(gate for gate in report["quality_gates"] if gate["key"] == "reviewer_approval")
    return gate, report


async def _event_count(db, item) -> int:
    return (
        await db.execute(select(func.count(WorkCodingReviewEvent.id)).where(WorkCodingReviewEvent.work_item_id == item.id))
    ).scalar_one()
