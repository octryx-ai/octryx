"""Reviewer suggestions for a Work Item's change, made for one Workspace."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AuditLog,
    User,
    UserProject,
    WorkItem,
    WorkItemChangeUnit,
    WorkRepositoryProfile,
    WorkReviewerOverride,
)
from ..linked_accounts.resolution import account_names, users_by_account_name
from .jira_values import blank_to_none, object_value, string_list
from .related_rows import REPOSITORY_PROFILE, load_usable_related
from .serializers import serialize_reviewer_override

DEFAULT_REVIEWER_POINTS = 40
OWNER_POINTS = 30
MEMBER_POINTS = 5
ADMIN_ROLE_POINTS = 5
ASSIGNEE_PENALTY = -50
MISSING_OWNERS = "repository_owners"
MISSING_UNITS = "change_units"


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _evidence(kind: str, points: int, reason: str) -> dict[str, Any]:
    return {"kind": kind, "points": points, "reason": reason, "details": {}}


async def user_aliases(db: AsyncSession, user_ids: set[str]) -> dict[str, set[str]]:
    if not user_ids:
        return {}
    aliases: dict[str, set[str]] = defaultdict(set)
    for user in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars():
        aliases[user.id].update(filter(None, (_norm(user.username), _norm(user.email), _norm(user.display_name))))
    for user_id, names in (await account_names(db, user_ids)).items():
        aliases[user_id].update(names)
    return aliases


async def users_named(db: AsyncSession, names: set[str]) -> dict[str, set[str]]:
    if not names:
        return {}
    users = (
        (
            await db.execute(
                select(User).where(
                    or_(
                        func.lower(User.username).in_(names),
                        func.lower(User.email).in_(names),
                        func.lower(User.display_name).in_(names),
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    named: dict[str, set[str]] = defaultdict(set)
    for user in users:
        for alias in (user.username, user.email, user.display_name):
            if _norm(alias) in names:
                named[_norm(alias)].add(user.id)
    for name, user_ids in (await users_by_account_name(db, names)).items():
        named[name].update(user_ids)
    return named


async def recommend_reviewers_for_work_item(
    db: AsyncSession, work_item_id: str, *, viewer: User | None, workspace_id: str | None
) -> dict[str, Any]:
    """Reviewer suggestions for the item in ``workspace_id`` (another Workspace's item answers like a missing one);
    repository records are loaded as ``viewer`` for that Workspace."""
    item = await db.get(WorkItem, work_item_id)
    if item is None or item.project_id != workspace_id:
        raise HTTPException(status_code=404, detail="Work Item not found")
    units = (
        (
            await db.execute(
                select(WorkItemChangeUnit)
                .where(WorkItemChangeUnit.work_item_id == item.id)
                .order_by(WorkItemChangeUnit.dependency_order.asc(), WorkItemChangeUnit.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    records: dict[str, WorkRepositoryProfile] = {}
    for profile_id in dict.fromkeys(unit.repository_profile_id for unit in units if unit.repository_profile_id):
        record = await load_usable_related(db, viewer, REPOSITORY_PROFILE, profile_id, for_workspace=workspace_id)
        if record is not None:
            records[profile_id] = record
    members = (
        {
            row.user_id: row.role
            for row in (
                await db.execute(select(UserProject).where(UserProject.project_id == workspace_id))
            ).scalars()
        }
        if workspace_id
        else {}
    )
    aliases = await user_aliases(db, set(members))
    candidates: dict[str, dict[str, Any]] = {}

    def candidate(key: str, *, user: User | None, name: str) -> dict[str, Any]:
        if key not in candidates:
            candidates[key] = {
                "profile_id": None,
                "user_id": user.id if user else None,
                "display_name": (user.display_name or user.username) if user else name,
                "primary_email": user.email if user else None,
                "score": 0,
                "available": True,
                "teams": [],
                "skills": [],
                "approval_roles": [],
                "review_load": {},
                "missing_identity_mappings": [],
                "scm_username": None,
                "evidence": [],
            }
        return candidates[key]

    users = (
        {user.id: user for user in (await db.execute(select(User).where(User.id.in_(set(members))))).scalars()}
        if members
        else {}
    )
    owners_declared = False
    for unit in units:
        record = records.get(unit.repository_profile_id or "")
        if record is None:
            continue
        repository = unit.repository_name or record.name
        for kind, names, points in (
            ("default_reviewer", record.default_reviewers_json, DEFAULT_REVIEWER_POINTS),
            ("repository_owner", record.owners_json, OWNER_POINTS),
        ):
            for name in string_list(names):
                owners_declared = True
                matched = [user_id for user_id, names_of in aliases.items() if _norm(name) in names_of]
                user = users.get(matched[0]) if len(matched) == 1 else None
                entry = candidate(user.id if user else f"name:{_norm(name)}", user=user, name=name)
                entry["score"] += points
                label = "default reviewer" if kind == "default_reviewer" else "owner"
                entry["evidence"].append(
                    _evidence(kind, points, f"Declared {label} {name} of repository {repository}.")
                )
                if kind == "default_reviewer" and not entry["scm_username"]:
                    entry["scm_username"] = name
    for user_id, role in members.items():
        user = users.get(user_id)
        if user is None or not user.is_active:
            continue
        entry = candidate(user_id, user=user, name=user.username)
        entry["approval_roles"] = [role] if role else []
        points = MEMBER_POINTS + (ADMIN_ROLE_POINTS if role in ("owner", "admin") else 0)
        entry["score"] += points
        entry["evidence"].append(_evidence("workspace_member", points, f"Workspace {role or 'member'}."))
    assignee = _norm(item.assignee)
    for key, entry in candidates.items():
        if assignee and (
            assignee in aliases.get(entry["user_id"] or "", set()) or assignee == _norm(entry["display_name"])
        ):
            entry["score"] += ASSIGNEE_PENALTY
            entry["evidence"].append(
                _evidence("assignee", ASSIGNEE_PENALTY, "Works on the item; not its first reviewer.")
            )
    recommendations = sorted(candidates.values(), key=lambda entry: (-entry["score"], entry["display_name"].lower()))
    missing = ([MISSING_UNITS] if not units else []) + ([MISSING_OWNERS] if units and not owners_declared else [])
    return {
        "work_item_id": item.id,
        "source_key": item.source_key,
        "change_unit_count": len(units),
        "recommendations": recommendations,
        "overrides": await list_reviewer_overrides(db, work_item_id),
        "missing_setup": missing,
    }


async def list_reviewer_overrides(db: AsyncSession, work_item_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(WorkReviewerOverride)
        .where(WorkReviewerOverride.work_item_id == work_item_id)
        .order_by(WorkReviewerOverride.created_at.desc())
    )
    return [serialize_reviewer_override(row) for row in (await db.execute(stmt)).scalars().all()]


async def apply_reviewer_override(
    db: AsyncSession, *, work_item_id: str, current_user: User, payload: dict[str, Any]
) -> dict[str, Any]:
    item = await db.get(WorkItem, work_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work Item not found")
    change_unit_id = blank_to_none(payload.get("change_unit_id"))
    if change_unit_id:
        unit = await db.get(WorkItemChangeUnit, change_unit_id)
        # An override records an assignment for this item's own unit only; it never approves.
        if unit is None or unit.work_item_id != item.id:
            raise HTTPException(status_code=404, detail="Change Unit not found for this Work Item")
    selected_user_id = blank_to_none(payload.get("selected_user_id"))
    selected_user = await db.get(User, selected_user_id) if selected_user_id else None
    selected_reviewer = str(
        payload.get("selected_reviewer")
        or ((selected_user.display_name or selected_user.username) if selected_user else "")
    ).strip()
    if not selected_reviewer:
        raise HTTPException(status_code=422, detail="selected_reviewer is required")
    evidence = object_value(payload.get("evidence"))
    if selected_user is not None:
        evidence = {**evidence, "user_id": selected_user.id}
    row = WorkReviewerOverride(
        work_item_id=item.id,
        change_unit_id=change_unit_id,
        selected_reviewer=selected_reviewer[:220],
        reason=blank_to_none(payload.get("reason")),
        evidence_json=evidence,
        actor_id=current_user.id,
    )
    db.add(row)
    await db.flush()
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="secure_work.reviewer_override_applied",
            resource_type="work_item",
            resource_id=item.id,
            project_id=item.project_id,
            details={
                "source_key": item.source_key,
                "override_id": row.id,
                "change_unit_id": row.change_unit_id,
                "selected_reviewer": row.selected_reviewer,
                "reason": row.reason,
                "evidence": dict(row.evidence_json or {}),
            },
        )
    )
    await db.flush()
    return serialize_reviewer_override(row)


__all__ = [
    "MISSING_OWNERS",
    "apply_reviewer_override",
    "list_reviewer_overrides",
    "recommend_reviewers_for_work_item",
    "user_aliases",
    "users_named",
]
