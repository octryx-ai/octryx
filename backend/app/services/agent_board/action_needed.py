"""What needs the current person, across their Workspaces, and its in-app notifications.

Items (newest first, at most :data:`MAX_ITEMS`):

- ``decision_request``: undecided, unredacted requests addressed to me, or addressed to ``admins`` or to no
  one in a Workspace where I am admin/owner;
- ``limit_reached_with_claim`` (Workspace admins/owners only): a session at its seat limit that still holds a
  live work-item claim, one item per claim;
- ``handoff_confirm`` and ``available_handoff``: see ``action_needed_handoffs``.

Every item has one in-app ``Notification`` per person. Its dedupe key is the kind plus the message or claim id,
carried in the deep ``link``; the title is secret-free (kind, work item key, the agent's user) and there is never
a body. :func:`sync_notifications` creates the missing ones and resolves (marks read) the ones whose item is
gone: answered, redacted, released or cleared. A person who turned in-app notifications off gets none.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentBoardMessage, AgentPresence, Notification, WorkItem, WorkItemClaim
from ...models.worker.teaming import NotificationPreference
from ...time_utils import utc_now
from ..agent_gateway.presence import STATE_LIMIT_REACHED, session_key_hash
from ..project.service import get_project_access_details
from .action_needed_handoffs import (
    ITEM_AVAILABLE_HANDOFF,
    ITEM_HANDOFF_CONFIRM,
    available_handoff_items,
    handoff_confirm_items,
)
from .claim_values import KIND_GATEWAY_SESSION, iso
from .envelope import KIND_DECISION, KIND_DECISION_REQUEST, user_refs
from .messages import ADMIN_ROLES, ROLE_ADMINS

ITEM_DECISION_REQUEST = "decision_request"
ITEM_LIMIT_REACHED_WITH_CLAIM = "limit_reached_with_claim"
NOTIFICATION_PREFIX = "agent_board."
MAX_ITEMS = 100
_TITLES = {
    ITEM_DECISION_REQUEST: "Decision needed",
    ITEM_LIMIT_REACHED_WITH_CLAIM: "Seat limit reached with a claim",
    ITEM_HANDOFF_CONFIRM: "Confirm takeover",
    ITEM_AVAILABLE_HANDOFF: "Handoff available",
}


def item_link(item: dict[str, Any]) -> str:
    base = f"/chat?area=agents&workspace_id={item['project']['id']}"
    if item.get("message_id"):
        return f"{base}&board_message_id={item['message_id']}"
    if item.get("takeover_id"):
        return f"{base}&takeover_id={item['takeover_id']}"
    if item["kind"] == ITEM_AVAILABLE_HANDOFF:
        return f"{base}&handoff_claim_id={item['claim_id']}"
    return f"{base}&claim_id={item['claim_id']}"


def _title(item: dict[str, Any]) -> str:
    parts = [_TITLES.get(item["kind"], item["kind"])]
    if item.get("work_item"):
        parts.append(str(item["work_item"]["key"]))
    agent = item.get("agent")
    if agent and agent.get("user"):
        parts.append(f"agent of {agent['user']['display_name']}")
    return " – ".join(parts)[:200]


async def _decision_requests(
    db: AsyncSession, user_id: str, projects: dict[str, dict[str, Any]], admin_projects: set[str]
) -> list[dict[str, Any]]:
    decided = select(AgentBoardMessage.reply_to).where(
        AgentBoardMessage.kind == KIND_DECISION, AgentBoardMessage.reply_to.is_not(None)
    )
    rows = (
        await db.execute(
            select(AgentBoardMessage)
            .where(
                AgentBoardMessage.project_id.in_(sorted(projects)),
                AgentBoardMessage.kind == KIND_DECISION_REQUEST,
                AgentBoardMessage.redacted_at.is_(None),
                AgentBoardMessage.id.not_in(decided),
            )
            .order_by(AgentBoardMessage.created_at.desc())
            .limit(MAX_ITEMS * 4)
        )
    ).scalars().all()
    mine = []
    for row in rows:
        unaddressed = row.to_user_id is None and row.to_agent_hash is None and row.to_role is None
        if row.to_user_id == user_id or (
            (row.to_role == ROLE_ADMINS or unaddressed) and row.project_id in admin_projects
        ):
            mine.append(row)
    users = await user_refs(db, [row.author_user_id for row in mine])
    items = await _work_items(db, [row.work_item_id for row in mine])
    return [
        {
            "kind": ITEM_DECISION_REQUEST,
            "project": projects[row.project_id],
            "message_id": row.id,
            "work_item": items.get(row.work_item_id),
            "agent": {"user": users.get(row.author_user_id), "agent_hash": row.author_agent_hash}
            if row.author_agent_hash else None,
            "created_at": iso(row.created_at),
        }
        for row in mine
    ]


async def _limit_reached_claims(
    db: AsyncSession, projects: dict[str, dict[str, Any]], admin_projects: set[str]
) -> list[dict[str, Any]]:
    if not admin_projects:
        return []
    sessions = (
        await db.execute(
            select(AgentPresence).where(
                AgentPresence.project_id.in_(sorted(admin_projects)),
                AgentPresence.state == STATE_LIMIT_REACHED,
                AgentPresence.stopped_at.is_(None),
            )
        )
    ).scalars().all()
    by_hash = {session_key_hash(row.session_key): row for row in sessions}
    if not by_hash:
        return []
    claims = (
        await db.execute(
            select(WorkItemClaim).where(
                WorkItemClaim.holder_kind == KIND_GATEWAY_SESSION,
                WorkItemClaim.holder_ref_hash.in_(sorted(by_hash)),
                WorkItemClaim.released_at.is_(None),
                WorkItemClaim.lease_until > utc_now(),
            )
        )
    ).scalars().all()
    users = await user_refs(db, [claim.holder_user_id for claim in claims])
    items = await _work_items(db, [claim.work_item_id for claim in claims])
    found = []
    for claim in claims:
        presence = by_hash[claim.holder_ref_hash]
        if claim.project_id != presence.project_id:
            continue
        found.append(
            {
                "kind": ITEM_LIMIT_REACHED_WITH_CLAIM,
                "project": projects[claim.project_id],
                "claim_id": claim.id,
                "work_item": items.get(claim.work_item_id),
                "agent": {"user": users.get(claim.holder_user_id), "agent_hash": claim.holder_ref_hash},
                "created_at": iso(presence.allowance_updated_at or presence.last_seen_at or claim.claimed_at),
            }
        )
    return found


async def _work_items(db: AsyncSession, item_ids: list[str | None]) -> dict[str, dict[str, str]]:
    ids = sorted({item_id for item_id in item_ids if item_id})
    if not ids:
        return {}
    statement = select(WorkItem.id, WorkItem.source_key, WorkItem.title).where(WorkItem.id.in_(ids))
    rows = (await db.execute(statement)).all()
    return {item_id: {"id": item_id, "key": key, "title": title} for item_id, key, title in rows}


async def action_needed(db: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    access = await get_project_access_details(user_id, db)
    projects = {str(entry["id"]): {"id": str(entry["id"]), "name": entry.get("name")} for entry in access}
    if not projects:
        return []
    admin_projects = {str(entry["id"]) for entry in access if entry.get("role") in ADMIN_ROLES}
    items = [
        *await _decision_requests(db, user_id, projects, admin_projects),
        *await _limit_reached_claims(db, projects, admin_projects),
        *await handoff_confirm_items(db, user_id, projects, admin_projects),
        *await available_handoff_items(db, user_id, projects),
    ]
    items.sort(key=lambda item: item["created_at"] or "", reverse=True)
    return items[:MAX_ITEMS]


async def _in_app_enabled(db: AsyncSession, user_id: str) -> bool:
    preference = await db.get(NotificationPreference, user_id)
    return preference is None or bool(preference.in_app_enabled)


async def sync_notifications(db: AsyncSession, user_id: str, items: list[dict[str, Any]]) -> None:
    """One notification per current item; open ones whose item is gone are resolved. Flushes."""
    wanted = {item_link(item): item for item in items}
    open_rows = (
        await db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.type.like(f"{NOTIFICATION_PREFIX}%"),
            )
        )
    ).scalars().all()
    known = {(row.type, row.link) for row in open_rows}
    now = utc_now()
    for row in open_rows:
        if not row.is_read and row.link not in wanted:
            row.is_read, row.read_at = True, now
    if await _in_app_enabled(db, user_id):
        for link, item in wanted.items():
            kind = f"{NOTIFICATION_PREFIX}{item['kind']}"
            if (kind, link) not in known:
                db.add(Notification(id=str(uuid.uuid4()), user_id=user_id, type=kind, title=_title(item),
                                    body=None, link=link, is_read=False, created_at=now))
    await db.flush()


async def resolve_message_notifications(db: AsyncSession, message: AgentBoardMessage) -> None:
    """Everyone's open notification for ``message`` is resolved (answered or redacted)."""
    await db.execute(
        update(Notification)
        .where(
            Notification.type.like(f"{NOTIFICATION_PREFIX}%"),
            Notification.link.like(f"%&board_message_id={message.id}"),
            Notification.is_read.is_(False),
        )
        .values(is_read=True, read_at=utc_now())
        .execution_options(synchronize_session=False)
    )


__all__ = [
    "ITEM_DECISION_REQUEST",
    "ITEM_LIMIT_REACHED_WITH_CLAIM",
    "action_needed",
    "item_link",
    "resolve_message_notifications",
    "sync_notifications",
]
