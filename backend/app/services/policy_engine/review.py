"""The review of a policy-set version, for the lifecycle drawer.

``review_view`` describes the governance approval a submit opened, from the viewer's side: who submitted it and
when, its status and the decider's comment (the approvals API stores the decision reason on the approval), the
author and submitter, the platform admins who may approve it (four-eyes: anyone but the author and the
submitter), and whether the viewer may approve (``can_approve``) — the same rule ``store_publish.check_publish_gate``
enforces at publish. The decision itself stays with the approvals API; nothing here changes the lifecycle.

``history_rows`` adds the author and reviewer names to the version list.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Approval, PolicySetVersion, Role, User, UserRole
from ...models.runtime.governed_revision import REVISION_STATE_IN_REVIEW
from ..governance.approval_rule import load_approval_rule
from ..governance.four_eyes import recorded_approval_mode, self_approval_source
from .principals import ADMIN_ROLE

FOUR_EYES_RULE = "A platform admin other than the author and the submitter must approve before anyone can publish."
SELF_APPROVAL_RULE = "The approval rule lets a single admin approve and publish their own version."


def _person(user_id: str | None, names: dict[str, str]) -> dict[str, str] | None:
    if not user_id:
        return None
    return {"id": str(user_id), "name": names.get(str(user_id)) or str(user_id)}


async def _names(db: AsyncSession, ids: set[str]) -> dict[str, str]:
    wanted = {item for item in ids if item}
    if not wanted:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(wanted)))).scalars()
    return {row.id: row.display_name or row.username for row in rows}


async def platform_admins(db: AsyncSession) -> list[tuple[str, str]]:
    """``(id, name)`` of the active platform admins, by name."""
    stmt = (select(User).join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id)
            .where(Role.name == ADMIN_ROLE, User.is_active.is_(True)))
    rows = {row.id: row.display_name or row.username for row in (await db.execute(stmt)).scalars()}
    return sorted(rows.items(), key=lambda item: (item[1].lower(), item[0]))


async def review_view(db: AsyncSession, row: PolicySetVersion, *, viewer_id: str) -> dict[str, Any] | None:
    if not row.approval_id:
        return None
    approval = await db.get(Approval, row.approval_id)
    if approval is None:
        return None
    own = {str(row.created_by or ""), str(row.submitted_by or ""), str(approval.requested_by or "")} - {""}
    admins = await platform_admins(db)
    names = await _names(db, own | {str(approval.approved_by or "")}) | dict(admins)
    pending = approval.status == "pending" and row.state == REVISION_STATE_IN_REVIEW
    # The platform approval rule (or the development exception) lets the author approve too.
    single_admin = await self_approval_source(db) is not None
    admin_ids = {user_id for user_id, _ in admins}
    return {
        "approval_id": approval.id,
        "status": approval.status,
        "requested_by": _person(approval.requested_by, names),
        "requested_at": approval.created_at.isoformat() if approval.created_at else None,
        "decided_by": _person(approval.approved_by, names),
        "decided_at": approval.resolved_at.isoformat() if approval.resolved_at else None,
        "comment": approval.reason or "",
        "author": _person(row.created_by, names),
        "submitter": _person(row.submitted_by, names),
        "approver_candidates": [{"id": user_id, "name": name} for user_id, name in admins if user_id not in own],
        "viewer": {"is_author": viewer_id == row.created_by, "is_submitter": viewer_id == row.submitted_by,
                   "can_approve": pending and viewer_id in admin_ids and (single_admin or viewer_id not in own)},
        "single_admin": single_admin,
        "approval_rule": await load_approval_rule(db),
        "approval_mode": recorded_approval_mode(approval, authors=(row.created_by, row.submitted_by)),
        "rule": SELF_APPROVAL_RULE if single_admin else FOUR_EYES_RULE,
    }


async def history_rows(db: AsyncSession, rows: list[PolicySetVersion], payloads: list[dict[str, Any]]) -> list[dict]:
    """The version list with ``author_name``, ``reviewer`` and ``reviewer_name`` (who approved its review)."""
    approvals = {item.id: item for item in (await db.execute(
        select(Approval).where(Approval.id.in_([row.approval_id for row in rows if row.approval_id])))).scalars()}
    reviewers = {row.version: approvals[row.approval_id].approved_by for row in rows
                 if row.approval_id in approvals and approvals[row.approval_id].status == "approved"}
    people = {str(row.created_by or "") for row in rows} | {str(item or "") for item in reviewers.values()}
    names = await _names(db, people)
    for row, payload in zip(rows, payloads, strict=True):
        reviewer = reviewers.get(row.version)
        payload.update(author_name=names.get(str(row.created_by or "")), reviewer=reviewer,
                       reviewer_name=names.get(str(reviewer)) if reviewer else None,
                       approval_mode=recorded_approval_mode(approvals.get(row.approval_id or ""),
                                                            authors=(row.created_by, row.submitted_by)))
    return payloads


__all__ = ["FOUR_EYES_RULE", "history_rows", "platform_admins", "review_view"]
